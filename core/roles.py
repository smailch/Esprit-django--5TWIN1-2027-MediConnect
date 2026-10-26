"""Rôles MediConnect <-> groupes et permissions Django.

Chaque rôle (User.role) correspond à un groupe Django qui porte ses permissions de modèle. Les groupes sont créés et
mis à jour après chaque « migrate » (signal post_migrate), et chaque compte est rangé dans le groupe de son rôle à
chaque enregistrement (signal post_save) : changer le rôle d'un compte change donc ses permissions.

Les pages vérifient le rôle (décorateurs de chaque app) et, pour la gestion des comptes, la permission Django
(PermissionRequiredMixin, voir backoffice/views_comptes.py). Un super-utilisateur a toutes les permissions.
"""
import logging

journal = logging.getLogger("mediconnect.securite")

# rôle -> (nom du groupe, permissions « app.codename »)
GROUPES = {
    "patient": ("Patients", [
        "patients.view_patient", "patients.change_patient",
        "patients.view_dossiermedical", "patients.change_dossiermedical",
        "patients.add_allergie", "patients.view_allergie", "patients.change_allergie", "patients.delete_allergie",
        "patients.add_mesure", "patients.view_mesure", "patients.change_mesure", "patients.delete_mesure",
        "patients.add_triage", "patients.view_triage",
        "infirmiers.add_interventiondomicile", "infirmiers.view_interventiondomicile",
        "pharmacies.view_ordonnance",
    ]),
    "medecin": ("Médecins", [
        "medecins.view_medecin", "medecins.change_medecin",
        "patients.view_patient", "patients.view_dossiermedical", "patients.view_triage", "patients.change_triage",
        "patients.add_consultation", "patients.view_consultation", "patients.change_consultation",
        "medecins.add_prescription", "medecins.view_prescription", "medecins.change_prescription",
        "pharmacies.add_ordonnance", "pharmacies.view_ordonnance",
    ]),
    "infirmier": ("Infirmiers", [
        "infirmiers.view_infirmier", "infirmiers.change_infirmier",
        "infirmiers.view_interventiondomicile", "infirmiers.change_interventiondomicile",
        "patients.add_mesure", "patients.view_mesure",
    ]),
    "pharmacie": ("Pharmacies", [
        "pharmacies.view_pharmacie", "pharmacies.change_pharmacie",
        "pharmacies.add_medicament", "pharmacies.view_medicament", "pharmacies.change_medicament", "pharmacies.delete_medicament",
        "pharmacies.view_ordonnance", "pharmacies.change_ordonnance",
        "pharmacies.add_remplacement", "pharmacies.view_remplacement",
    ]),
    "laboratoire": ("Laboratoires", []),
    "admin": ("Administrateurs", [
        "core.view_user", "core.change_user", "core.view_journalconnexion",
        "patients.view_patient", "patients.view_triage", "patients.change_triage", "patients.change_reglagetriage",
        "patients.view_symptome", "patients.change_symptome",
        "medecins.view_medecin", "medecins.change_medecin",
        "infirmiers.view_infirmier", "infirmiers.change_infirmier",
        "infirmiers.view_interventiondomicile", "infirmiers.change_interventiondomicile",
        "pharmacies.view_pharmacie", "pharmacies.change_pharmacie", "pharmacies.view_ordonnance",
    ]),
}


def groupe_du_role(role):
    from django.contrib.auth.models import Group

    nom = GROUPES.get(role, (None,))[0]
    return Group.objects.get_or_create(name=nom)[0] if nom else None


def synchroniser_groupes():
    """Crée les groupes et leur donne exactement leurs permissions. Renvoie {nom du groupe: nombre de permissions}."""
    from django.contrib.auth.models import Group, Permission

    bilan = {}
    for nom, codes in GROUPES.values():
        groupe = Group.objects.get_or_create(name=nom)[0]
        permissions = []
        for code in codes:
            app, codename = code.split(".")
            permission = Permission.objects.filter(content_type__app_label=app, codename=codename).first()
            if permission is None:
                journal.warning("Permission inconnue pour le groupe %s : %s", nom, code)
                continue
            permissions.append(permission)
        groupe.permissions.set(permissions)
        bilan[nom] = len(permissions)
    return bilan


def ranger(utilisateur):
    """Met le compte dans le groupe de son rôle (et dans aucun autre groupe de rôle)."""
    noms = {nom for nom, _ in GROUPES.values()}
    voulu = groupe_du_role(utilisateur.role)
    actuels = set(utilisateur.groups.filter(name__in=noms))
    if voulu is not None and voulu not in actuels:
        utilisateur.groups.add(voulu)
    a_retirer = [g for g in actuels if g != voulu]
    if a_retirer:
        utilisateur.groups.remove(*a_retirer)
    return voulu


def ranger_tous():
    from django.contrib.auth import get_user_model

    n = 0
    for utilisateur in get_user_model().objects.all():
        ranger(utilisateur)
        n += 1
    return n
