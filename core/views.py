from django.contrib import messages
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse, reverse_lazy

from .forms import ChangementMotDePasseForm, ConnexionForm, DemandeReinitialisationForm, NouveauMotDePasseForm


class ConnexionView(LoginView):
    """Connexion commune à tous les rôles."""

    template_name = "core/connexion.html"
    authentication_form = ConnexionForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        """Destination après connexion, selon le rôle (sauf si ?next=… est fourni)."""
        user = self.request.user
        role = getattr(user, "role", None)
        # Le personnel passe en premier : un super-utilisateur créé en ligne de commande
        # a le rôle « patient » par défaut, mais il doit arriver dans l'espace administrateur.
        if user.is_staff or user.is_superuser or role == user.Role.ADMIN:
            return reverse("backoffice:tableau_de_bord")
        if role == user.Role.PATIENT:
            return reverse("patients:tableau_de_bord")
        if role == user.Role.INFIRMIER:
            return reverse("infirmiers:tableau_de_bord")
        if role == user.Role.PHARMACIE:  # validée ou non : le tableau de bord explique l'attente de validation
            return reverse("pharmacies:tableau_de_bord")
        if role == user.Role.MEDECIN:
            return reverse("medecins:tableau_de_bord")
        return reverse("home")


class DeconnexionView(LogoutView):
    """Déconnexion en POST uniquement."""


class ChangementMotDePasseView(PasswordChangeView):
    """Changer son mot de passe (il faut connaître l'ancien). La session reste ouverte."""

    template_name = "core/mot_de_passe.html"
    form_class = ChangementMotDePasseForm
    success_url = reverse_lazy("core:mot_de_passe")

    def form_valid(self, form):
        messages.success(self.request, "Votre mot de passe a été changé.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        utilisateur = self.request.user
        if getattr(utilisateur, "patient", None):  # chacun garde son menu et revient à son espace
            cadre, retour = "patients/layout.html", reverse("patients:compte")
        elif getattr(utilisateur, "medecin", None):
            cadre, retour = "medecins/layout.html", reverse("medecins:profil")
        elif getattr(utilisateur, "infirmier", None):
            cadre, retour = "infirmiers/layout.html", reverse("infirmiers:profil")
        else:
            cadre, retour = "core/layout.html", reverse("home")
        contexte["cadre"] = cadre
        contexte["retour"] = retour
        return contexte


class ReinitialisationView(PasswordResetView):
    """« Mot de passe oublié » : envoie par e-mail un lien valable deux heures (voir PASSWORD_RESET_TIMEOUT).

    La réponse est la même que l'adresse soit connue ou non : on ne révèle pas qui a un compte."""

    template_name = "core/reinitialisation.html"
    form_class = DemandeReinitialisationForm
    email_template_name = "core/email/reinitialisation.txt"
    html_email_template_name = "core/email/reinitialisation.html"
    subject_template_name = "core/email/reinitialisation_objet.txt"
    success_url = reverse_lazy("core:reinitialisation_envoyee")


class ReinitialisationEnvoyeeView(PasswordResetDoneView):
    template_name = "core/reinitialisation_envoyee.html"


class ReinitialisationConfirmationView(PasswordResetConfirmView):
    template_name = "core/reinitialisation_confirmation.html"
    form_class = NouveauMotDePasseForm
    success_url = reverse_lazy("core:reinitialisation_terminee")


class ReinitialisationTermineeView(PasswordResetCompleteView):
    template_name = "core/reinitialisation_terminee.html"


def echec_csrf(request, reason=""):
    """Jeton CSRF absent ou expiré (settings.CSRF_FAILURE_VIEW) : page claire au lieu de la page technique de Django."""
    return render(request, "403_csrf.html", status=403)


def sante(request):
    """Sonde de santé pour l'hébergeur (Railway) : 200 si l'application répond et que la base est joignable."""
    from django.db import connection

    try:
        connection.ensure_connection()
        base = "ok"
    except Exception:  # la sonde rend compte de l'état, elle ne plante pas
        base = "injoignable"
    return JsonResponse({"application": "ok", "base": base}, status=200 if base == "ok" else 503)
