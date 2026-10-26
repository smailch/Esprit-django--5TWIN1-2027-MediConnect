"""Fabriques des tests d'intégration : des comptes complets (utilisateur + profil) dans la base de test.

Utilisées par les fichiers tests_integration.py de chaque app, avec django.test.TestCase et le client HTTP.
"""
import datetime
import itertools

from django.utils import timezone

from core.models import User

MOT_DE_PASSE = "Mediconnect-Test-2026!"
_numeros = itertools.count(1)


def _utilisateur(role, username=None, **kw):
    n = next(_numeros)
    username = username or f"{role}{n}"
    kw.setdefault("first_name", username.capitalize())
    kw.setdefault("last_name", "Test")
    kw.setdefault("email", f"{username}@exemple.tn")
    return User.objects.create_user(username, password=MOT_DE_PASSE, role=role, **kw)


def un_patient(username=None, ville="Tunis", **kw):
    from patients.models import Patient

    user = _utilisateur(User.Role.PATIENT, username, **kw)
    return Patient.objects.create(
        user=user, date_naissance=datetime.date(1980, 5, 17), sexe="F", telephone="20123456",
        adresse="7 rue de Rome", ville=ville,
    )


def un_medecin(username=None, est_valide=True, **kw):
    from medecins.models import Medecin

    user = _utilisateur(User.Role.MEDECIN, username, est_valide=est_valide, **kw)
    return Medecin.objects.create(user=user, code=user.username, specialite="Médecine générale", ville="Tunis")


def un_infirmier(username=None, ville="Tunis", zones=(), est_valide=True, **kw):
    from infirmiers.models import Infirmier

    user = _utilisateur(User.Role.INFIRMIER, username, est_valide=est_valide, **kw)
    return Infirmier.objects.create(
        user=user, telephone="22333444", numero_ordre=f"ORD-{user.pk}", ville=ville, zones=list(zones),
        soins=["injection", "pansement", "surveillance"],
    )


def une_pharmacie(username=None, **kw):
    from pharmacies.models import Pharmacie

    user = _utilisateur(User.Role.PHARMACIE, username, **kw)
    return Pharmacie.objects.create(user=user, nom=f"Pharmacie {user.username}", adresse="1 avenue Habib Bourguiba",
                                    ville="Tunis", telephone="71123456")


def un_admin(username=None, **kw):
    return _utilisateur(User.Role.ADMIN, username, **kw)


def demain(heure=9, minute=0):
    jour = timezone.localdate() + datetime.timedelta(days=1)
    return timezone.make_aware(datetime.datetime.combine(jour, datetime.time(heure, minute)))
