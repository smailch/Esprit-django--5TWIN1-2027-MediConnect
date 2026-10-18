"""Médecins FICTIFS, uniquement pour tester le parcours patient.

À remplacer par le vrai modèle de l'app `medecins` (module de Mourad) :
il suffira de garder les mêmes clés (id, nom, specialite, ville, disponible).
"""

MEDECINS = [
    {"id": "m1", "nom": "Dr Sara Benali", "specialite": "Médecine générale", "ville": "Tunis", "disponible": True},
    {"id": "m2", "nom": "Dr Karim Trabelsi", "specialite": "Cardiologie", "ville": "Tunis", "disponible": True},
    {"id": "m3", "nom": "Dr Leïla Mansouri", "specialite": "Pédiatrie", "ville": "Sfax", "disponible": False},
    {"id": "m4", "nom": "Dr Youssef Haddad", "specialite": "Médecine générale", "ville": "Sousse", "disponible": True},
    {"id": "m5", "nom": "Dr Amina Gharbi", "specialite": "Pneumologie", "ville": "Sfax", "disponible": True},
    {"id": "m6", "nom": "Dr Walid Jelassi", "specialite": "Urgences", "ville": "Tunis", "disponible": True},
]


def tous():
    return list(MEDECINS)


def trouver(medecin_id):
    return next((m for m in MEDECINS if m["id"] == medecin_id), None)


def specialites():
    return sorted({m["specialite"] for m in MEDECINS})


def villes():
    return sorted({m["ville"] for m in MEDECINS})


def filtrer(specialite="", ville=""):
    return [
        m
        for m in MEDECINS
        if (not specialite or m["specialite"] == specialite)
        and (not ville or m["ville"] == ville)
    ]
