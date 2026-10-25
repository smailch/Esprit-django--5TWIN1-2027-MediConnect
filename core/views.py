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
        est_patient = hasattr(self.request.user, "patient")  # un patient garde son menu et revient à « Mon compte »
        contexte["cadre"] = "patients/layout.html" if est_patient else "core/layout.html"
        contexte["retour"] = reverse("patients:compte") if est_patient else reverse("home")
        return contexte


class ReinitialisationView(PasswordResetView):
    """« Mot de passe oublié » : envoie par e-mail un lien valable deux heures (voir PASSWORD_RESET_TIMEOUT).

    La réponse est la même que l'adresse soit connue ou non : on ne révèle pas qui a un compte."""

    template_name = "core/reinitialisation.html"
    form_class = DemandeReinitialisationForm
    email_template_name = "core/email/reinitialisation.txt"
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
