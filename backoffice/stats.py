"""Statistiques du tableau de bord (fonctions pures, testables sans base de données)."""

from collections import Counter

NIVEAUX = (1, 2, 3, 4, 5)
LIBELLES_NIVEAU = {1: "Vital", 2: "Très urgent", 3: "Urgent", 4: "Standard", 5: "Non urgent"}
STATUTS_ACTIFS = ("en_attente", "en_consultation")
SEUIL_URGENT = 2  # niveaux 1 et 2


def niveau_effectif(niveau, niveau_medecin):
    """Le niveau requalifié par le médecin prime sur celui du triage."""
    return niveau_medecin or niveau


def repartition_par_niveau(lignes):
    """lignes : itérable de (niveau, niveau_medecin, statut) ; ne compte que les demandes actives.

    Renvoie une liste de dicts {niveau, libelle, nombre, pourcentage}, du niveau 1 au 5.
    Le pourcentage est relatif à la barre la plus longue (pour dessiner les barres)."""
    compteur = Counter()
    for niveau, niveau_medecin, statut in lignes:
        if statut in STATUTS_ACTIFS:
            n = niveau_effectif(niveau, niveau_medecin)
            if n in NIVEAUX:
                compteur[n] += 1
    maximum = max(compteur.values(), default=0)
    return [
        {
            "niveau": n,
            "libelle": LIBELLES_NIVEAU[n],
            "nombre": compteur[n],
            "pourcentage": round(100 * compteur[n] / maximum) if maximum else 0,
        }
        for n in NIVEAUX
    ]


def chiffres_cles(lignes, nb_patients):
    """Chiffres clés du tableau de bord à partir de (niveau, niveau_medecin, statut)."""
    lignes = list(lignes)
    actives = [(a, b, c) for a, b, c in lignes if c in STATUTS_ACTIFS]
    return {
        "total": len(lignes),
        "en_attente": sum(1 for _, _, statut in lignes if statut == "en_attente"),
        "urgentes": sum(
            1
            for niveau, niveau_medecin, statut in actives
            if (niveau_effectif(niveau, niveau_medecin) or 5) <= SEUIL_URGENT
        ),
        "terminees": sum(1 for _, _, statut in lignes if statut == "termine"),
        "annulees": sum(1 for _, _, statut in lignes if statut == "annule"),
        "patients": nb_patients,
    }


def nombre_par_patient(ids_patients):
    """Nombre de demandes par identifiant de patient."""
    return Counter(str(i) for i in ids_patients)
