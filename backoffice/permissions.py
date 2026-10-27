"""Droits d'accès à l'espace administrateur."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def est_administrateur(user):
    """Personnel du site : super-utilisateur, membre du staff ou rôle « administrateur »."""
    if not getattr(user, "is_authenticated", False):
        return False
    if not user.is_active:
        return False
    return bool(user.is_staff or user.is_superuser or getattr(user, "role", None) == "admin")


def administrateur_requis(vue):
    """Visiteur anonyme -> page de connexion ; compte non autorisé -> 403."""

    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect_to_login(request.get_full_path())
        if not est_administrateur(request.user):
            raise PermissionDenied("Espace réservé aux administrateurs.")
        return vue(request, *args, **kwargs)

    return enveloppe
