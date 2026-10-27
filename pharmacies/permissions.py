"""Droits d'accès du module pharmacies : chaque page dit quels « espaces » elle accepte.

Quatre espaces : administrateur, médecin (validé), pharmacie (compte validé ET fiche pharmacie) et patient.
Visiteur anonyme -> page de connexion ; compte d'un autre espace -> 403.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.shortcuts import redirect

from backoffice.permissions import est_administrateur

ADMIN, MEDECIN, PHARMACIE, PATIENT = "admin", "medecin", "pharmacie", "patient"
ENTREE_ADMIN = "backoffice_pharmacies"  # espace de noms du module monté dans le back-office (mediconnect/urls.py)
PRESCRIPTEURS = (ADMIN, MEDECIN)
TOUS = (ADMIN, MEDECIN, PHARMACIE, PATIENT)

MESSAGE_EN_ATTENTE = "Votre compte pharmacie attend la validation d'un administrateur."


def pharmacie_de(user):
    """La fiche pharmacie du compte, ou None."""
    try:
        return user.pharmacie
    except (ObjectDoesNotExist, AttributeError):
        return None


def patient_de(user):
    """Le patient du compte, ou None."""
    try:
        return user.patient
    except (ObjectDoesNotExist, AttributeError):
        return None


def espace_de(user):
    """L'espace du compte connecté ("" : aucun accès au module)."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return ""
    if est_administrateur(user):
        return ADMIN
    role = getattr(user, "role", None)
    if role == MEDECIN:
        return MEDECIN if user.est_valide else ""
    if role == PHARMACIE:
        return PHARMACIE if user.est_valide and pharmacie_de(user) is not None else ""
    return PATIENT if patient_de(user) is not None else ""


def espace_requis(*autorises):
    """Réserve une vue à certains espaces. L'espace est rangé dans request.espace (vues et gabarits s'en servent)."""

    def decorateur(vue):
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if not getattr(request.user, "is_authenticated", False):
                return redirect_to_login(request.get_full_path())
            espace = espace_de(request.user)
            if espace not in autorises:
                en_attente = getattr(request.user, "role", None) == PHARMACIE and not request.user.est_valide
                raise PermissionDenied(MESSAGE_EN_ATTENTE if en_attente else "Cette page ne fait pas partie de votre espace.")
            # L'administrateur travaille dans le back-office (/backoffice/pharmacies/), les autres comptes sous /pharmacies/.
            entree = getattr(getattr(request, "resolver_match", None), "namespace", None)
            if entree == ENTREE_ADMIN and espace != ADMIN:
                raise PermissionDenied("Espace réservé aux administrateurs.")
            if entree == "pharmacies" and espace == ADMIN and request.method in ("GET", "HEAD"):
                return redirect("/backoffice" + request.get_full_path())
            request.espace = espace
            return vue(request, *args, **kwargs)

        return enveloppe

    return decorateur
