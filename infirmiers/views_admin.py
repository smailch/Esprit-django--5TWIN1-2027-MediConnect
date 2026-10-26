"""Espace administrateur : les alertes relevées dans les comptes rendus de soins à domicile.

Les pages utilisent le cadre du back-office (backoffice/layout.html) et ses droits d'accès : c'est là que
l'administrateur supervise la plateforme, en attendant l'espace médecin."""

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from backoffice.permissions import administrateur_requis
from core.forms import StyledFormMixin
from core.utils import objet_ou_404

from .models import InterventionDomicile, NiveauAlerte

Statut = InterventionDomicile.Statut
ETATS = (("a_traiter", "À traiter"), ("traitees", "Traitées"), ("toutes", "Toutes"))
PAR_PAGE = 20


class SuiteAlerteForm(StyledFormMixin, forms.Form):
    suite = forms.CharField(
        label="Suite donnée", max_length=300, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Ex. médecin traitant prévenu, consultation fixée demain, patient orienté vers les urgences.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


def _avec_alerte():
    return InterventionDomicile.objects.filter(
        statut=Statut.REALISEE, niveau_alerte__in=[NiveauAlerte.SIGNALER, NiveauAlerte.SURVEILLER]
    ).select_related("patient__user", "infirmier__user")


@administrateur_requis
def alertes(request):
    etat = request.GET.get("etat", "a_traiter")
    if etat not in dict(ETATS):
        etat = "a_traiter"
    niveau = request.GET.get("niveau", "")
    if niveau not in (NiveauAlerte.SIGNALER, NiveauAlerte.SURVEILLER):
        niveau = ""

    toutes = list(_avec_alerte())
    a_traiter = [i for i in toutes if not i.alerte_traitee_le]
    liste = {"a_traiter": a_traiter, "traitees": [i for i in toutes if i.alerte_traitee_le], "toutes": toutes}[etat]
    if niveau:
        liste = [i for i in liste if i.niveau_alerte == niveau]
    # Les plus graves d'abord, puis les plus récentes.
    liste.sort(key=lambda i: (i.niveau_alerte != NiveauAlerte.SIGNALER, -i.realisee_le.timestamp()))
    page = Paginator(liste, PAR_PAGE).get_page(request.GET.get("page"))
    return render(request, "infirmiers/admin/alertes.html", {
        "page": page,
        "etats": ETATS,
        "filtre": {"etat": etat, "niveau": niveau},
        "parametres": urlencode({"etat": etat, "niveau": niveau}),
        "compteurs": {
            "signaler": sum(1 for i in a_traiter if i.niveau_alerte == NiveauAlerte.SIGNALER),
            "surveiller": sum(1 for i in a_traiter if i.niveau_alerte == NiveauAlerte.SURVEILLER),
        },
    })


@administrateur_requis
def alerte(request, pk):
    intervention = objet_ou_404(_avec_alerte(), pk=pk)
    return render(request, "infirmiers/admin/alerte.html", {"i": intervention, "form": SuiteAlerteForm()})


@administrateur_requis
@require_POST
def alerte_traiter(request, pk):
    intervention = objet_ou_404(_avec_alerte(), pk=pk)
    form = SuiteAlerteForm(request.POST)
    if form.is_valid():
        try:
            intervention.traiter_alerte(request.user.get_full_name() or request.user.get_username(), form.cleaned_data["suite"])
        except ValidationError as erreur:
            form.add_error(None, " ".join(erreur.messages))
        else:
            InterventionDomicile.objects.filter(pk=intervention.pk).update(
                alerte_traitee_le=intervention.alerte_traitee_le,
                alerte_traitee_par=intervention.alerte_traitee_par,
                alerte_suite=intervention.alerte_suite,
            )
            messages.success(request, f"Alerte de {intervention.patient} marquée comme traitée.")
            return redirect("infirmiers:alertes")
    return render(request, "infirmiers/admin/alerte.html", {"i": intervention, "form": form})
