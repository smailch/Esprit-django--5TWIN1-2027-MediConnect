from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse

from .forms import ConnexionForm


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
