"""Gestion des comptes par l'administrateur : tous les utilisateurs, leur validation, leur activation, et le journal
des connexions.

Contrôle d'accès en deux temps (impossible de passer par l'adresse directe) :
1. LoginRequiredMixin : un visiteur anonyme est renvoyé vers la page de connexion ;
2. PermissionRequiredMixin : il faut la permission Django (« core.view_user », « core.change_user »,
   « core.view_journalconnexion »), que porte le groupe « Administrateurs » (voir core/roles.py). Sinon : 403.
"""
import datetime
from collections import Counter
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from core.models import JournalConnexion, User
from core.utils import objet_ou_404
from infirmiers import notifications as notifications_soins
from infirmiers.models import InterventionDomicile
from patients import compte as gestion_compte

from .forms import PROFESSIONNELS, FiltreCompteForm, FiltreJournalForm


class AccesAdministrateurMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Anonyme -> connexion ; connecté sans la permission -> 403 (PermissionDenied)."""


class ComptesView(AccesAdministrateurMixin, ListView):
    permission_required = "core.view_user"
    template_name = "backoffice/comptes.html"
    context_object_name = "comptes"
    paginate_by = 15

    def get_queryset(self):
        self.filtre = FiltreCompteForm(self.request.GET or None)
        comptes = User.objects.exclude(role=User.Role.LABORATOIRE).order_by("-date_joined")
        if self.filtre.is_valid():
            comptes = self.filtre.appliquer(comptes)
        return comptes

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        tous = User.objects.exclude(role=User.Role.LABORATOIRE)
        depuis = timezone.now() - datetime.timedelta(hours=24)
        actifs = self.filtre.parametres()
        contexte.update(
            filtre=self.filtre,
            filtres_actifs=bool(actifs),
            parametres=urlencode(actifs),
            page=contexte["page_obj"],
            chiffres={
                "total": tous.count(),
                "a_valider": tous.filter(est_valide=False, is_active=True, role__in=PROFESSIONNELS).count(),
                "desactives": tous.filter(is_active=False).count(),
                "echecs_24h": JournalConnexion.objects.filter(
                    evenement__in=[JournalConnexion.Evenement.ECHEC, JournalConnexion.Evenement.BLOCAGE], quand__gte=depuis
                ).count(),
            },
            par_role=_par_role(tous),
        )
        return contexte


def _par_role(comptes):
    nombres = Counter(comptes.values_list("role", flat=True))
    return [(libelle, nombres.get(valeur, 0)) for valeur, libelle in User.Role.choices if valeur != User.Role.LABORATOIRE]


class CompteActionView(AccesAdministrateurMixin, View):
    """Valider, retirer la validation, désactiver ou réactiver un compte (POST uniquement)."""

    permission_required = "core.change_user"
    http_method_names = ["post"]
    ACTIONS = ("valider", "retirer", "desactiver", "reactiver")

    def post(self, request, pk, action):
        compte = objet_ou_404(User, pk=pk)
        if action not in self.ACTIONS:
            messages.error(request, "Action inconnue.")
        else:
            try:
                messages.success(request, getattr(self, action)(compte))
            except ValidationError as erreur:
                messages.error(request, erreur.messages[0])
        return redirect(self._retour())

    def _retour(self):
        suivante = self.request.POST.get("next", "")
        if suivante and url_has_allowed_host_and_scheme(suivante, allowed_hosts={self.request.get_host()}):
            return suivante
        return "backoffice:comptes"

    def _verifier_modifiable(self, compte):
        if compte.pk == self.request.user.pk:
            raise ValidationError("Vous ne pouvez pas modifier votre propre compte ici.")
        if (compte.is_superuser or compte.is_staff) and not self.request.user.is_superuser:
            raise ValidationError("Seul un super-utilisateur peut modifier le compte d'un membre du personnel.")

    def valider(self, compte):
        if compte.role not in PROFESSIONNELS:
            raise ValidationError("Seuls les comptes professionnels sont soumis à validation.")
        if compte.est_valide:
            raise ValidationError(f"Le compte {compte.username} est déjà validé.")
        compte.est_valide = True
        compte.save(update_fields=["est_valide"])
        return f"Le compte {compte.get_full_name() or compte.username} ({compte.get_role_display().lower()}) est validé."

    def retirer(self, compte):
        self._verifier_modifiable(compte)
        if compte.role not in PROFESSIONNELS or not compte.est_valide:
            raise ValidationError("Ce compte n'a pas de validation à retirer.")
        compte.est_valide = False
        compte.save(update_fields=["est_valide"])
        return f"La validation de {compte.username} est retirée : il ne peut plus exercer sur la plateforme."

    def desactiver(self, compte):
        self._verifier_modifiable(compte)
        if not compte.is_active:
            raise ValidationError("Ce compte est déjà désactivé.")
        liberes = _liberer_passages(self.request, compte) if compte.role == User.Role.INFIRMIER else 0
        annulees = gestion_compte.desactiver(compte)  # patient : ses demandes en attente sont annulées
        details = []
        if annulees:
            details.append(f"{annulees} demande(s) en attente annulée(s)")
        if liberes:
            details.append(f"{liberes} passage(s) à venir rendu(s) aux autres infirmiers")
        return f"Le compte {compte.username} est désactivé" + (f" : {', '.join(details)}." if details else ".")

    def reactiver(self, compte):
        self._verifier_modifiable(compte)
        if compte.is_active:
            raise ValidationError("Ce compte est déjà actif.")
        gestion_compte.reactiver(compte)
        return f"Le compte {compte.username} est réactivé."


def _liberer_passages(request, compte):
    """Un infirmier désactivé ne viendra plus : ses passages à venir retournent aux infirmiers de la zone, et chaque
    patient est prévenu (comme lorsque l'infirmier se désiste lui-même)."""
    from infirmiers.views import lien_patient

    fiche = getattr(compte, "infirmier", None)
    if fiche is None:
        return 0
    n = 0
    a_venir = InterventionDomicile.objects.filter(
        infirmier=fiche, statut=InterventionDomicile.Statut.ACCEPTEE, date_prevue__gte=timezone.now()
    ).select_related("patient__user")
    for intervention in a_venir:
        ancien = intervention.date_prevue
        intervention.liberer()
        intervention.save()
        notifications_soins.passage_libere(intervention, lien_patient(request, intervention), fiche, ancien)
        n += 1
    return n


class JournalConnexionsView(AccesAdministrateurMixin, ListView):
    permission_required = "core.view_journalconnexion"
    template_name = "backoffice/journal_connexions.html"
    context_object_name = "entrees"
    paginate_by = 25

    def get_queryset(self):
        self.filtre = FiltreJournalForm(self.request.GET or None)
        entrees = JournalConnexion.objects.select_related("utilisateur").order_by("-quand")
        if self.filtre.is_valid():
            entrees = self.filtre.appliquer(entrees)
        return entrees

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        actifs = self.filtre.parametres()
        contexte.update(filtre=self.filtre, filtres_actifs=bool(actifs), parametres=urlencode(actifs), page=contexte["page_obj"],
                        essais_max=settings.CONNEXION_ESSAIS_MAX, blocage_minutes=settings.CONNEXION_BLOCAGE_MINUTES)
        return contexte
