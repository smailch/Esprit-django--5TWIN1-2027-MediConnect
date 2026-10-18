"""Échelles d'auto-évaluation, de 0 à 5, en mots simples.

Un patient ne connaît pas son pouls ni sa tension, mais il sait dire à quel
point il a mal ou à quel point il se sent mal. Ces libellés sont partagés par
le formulaire, le moteur de triage, la page de résultat et l'admin.
"""

NIVEAU_MIN = 0
NIVEAU_MAX = 5

ECHELLES = {
    "douleur": {
        "question": "Quelle est l'intensité de votre douleur ?",
        "court": "douleur",
        "niveaux": [
            "Aucune",
            "Légère",
            "Gênante",
            "Forte",
            "Très forte",
            "Insupportable",
        ],
    },
    "fievre": {
        "question": "Avez-vous de la fièvre ou des frissons ?",
        "court": "fièvre ressentie",
        "niveaux": [
            "Pas de fièvre",
            "Un peu chaud",
            "Fièvre légère",
            "Fièvre",
            "Forte fièvre",
            "Très forte fièvre, frissons",
        ],
    },
    "respiration": {
        "question": "Avez-vous du mal à respirer ?",
        "court": "gêne respiratoire",
        "niveaux": [
            "Aucune gêne",
            "Légère gêne",
            "Gêne à l'effort",
            "Gêne au repos",
            "Difficulté importante",
            "Je suffoque",
        ],
    },
    "etat_general": {
        "question": "Globalement, à quel point vous sentez-vous mal ?",
        "court": "état général",
        "niveaux": [
            "Je me sens bien",
            "Un peu mal",
            "Mal",
            "Assez mal",
            "Très mal",
            "Extrêmement mal",
        ],
    },
}


def choix(nom):
    """Choix (valeur, libellé) d'une échelle, pour un champ de formulaire."""
    return list(enumerate(ECHELLES[nom]["niveaux"]))


def libelle(nom, valeur):
    return ECHELLES[nom]["niveaux"][valeur]
