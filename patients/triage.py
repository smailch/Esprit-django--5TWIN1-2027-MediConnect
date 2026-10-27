"""Moteur de triage à base de règles pondérées.

ATTENTION : seuils et pondérations de DÉMONSTRATION, à faire valider par un
professionnel de santé avant tout usage réel.

Niveaux : 1 = vital … 5 = non urgent (plus le chiffre est petit, plus c'est urgent).
"""

from dataclasses import dataclass, field

from .echelles import ECHELLES, NIVEAU_MAX, libelle

# Score minimal pour atteindre un niveau (du plus urgent au moins urgent).
SEUILS = [(20, 2), (12, 3), (5, 4)]
NIVEAU_PAR_DEFAUT = 5
NIVEAU_DRAPEAU_ROUGE_PAR_DEFAUT = 2


# Auto-évaluation du patient, échelles de 0 à 5.
# Pour chaque valeur : (points ajoutés au score, niveau d'urgence minimal imposé ou None).
POINTS_ECHELLES = {
    "douleur": {
        0: (0, None), 1: (0, None), 2: (1, None), 3: (3, None), 4: (6, None), 5: (9, 2),
    },
    "fievre": {
        0: (0, None), 1: (1, None), 2: (3, None), 3: (5, None), 4: (7, None), 5: (9, 3),
    },
    "respiration": {
        0: (0, None), 1: (2, None), 2: (4, None), 3: (8, 3), 4: (12, 2), 5: (16, 1),
    },
    "etat_general": {
        0: (0, None), 1: (0, None), 2: (2, None), 3: (4, None), 4: (7, 3), 5: (10, 2),
    },
}


@dataclass
class Resultat:
    score: int
    niveau: int
    explication: str
    drapeaux_rouges: list = field(default_factory=list)


def _niveau_depuis_score(score):
    for seuil, niveau in SEUILS:
        if score >= seuil:
            return niveau
    return NIVEAU_PAR_DEFAUT


def _evaluer_constantes(c):
    """Renvoie (points, niveau_minimal ou None, [messages])."""
    points, minimal, notes = 0, None, []

    def noter(pts, texte, niveau_min=None):
        nonlocal points, minimal
        points += pts
        notes.append(texte)
        if niveau_min is not None:
            minimal = niveau_min if minimal is None else min(minimal, niveau_min)

    t = c.get("temperature")
    if t is not None:
        if t >= 41:
            noter(8, f"température très élevée ({t} °C)", 2)
        elif t >= 39.5:
            noter(6, f"forte fièvre ({t} °C)")
        elif t >= 38:
            noter(3, f"fièvre ({t} °C)")
        elif t < 35:
            noter(6, f"température basse ({t} °C)")

    spo2 = c.get("saturation_oxygene")
    if spo2 is not None:
        if spo2 < 90:
            noter(15, f"saturation en oxygène critique ({spo2} %)", 1)
        elif spo2 < 94:
            noter(8, f"saturation en oxygène basse ({spo2} %)")

    fc = c.get("frequence_cardiaque")
    if fc is not None:
        if fc > 130 or fc < 40:
            noter(8, f"fréquence cardiaque anormale ({fc}/min)")
        elif fc > 110 or fc < 50:
            noter(4, f"fréquence cardiaque inhabituelle ({fc}/min)")

    sys_ = c.get("tension_systolique")
    if sys_ is not None:
        if sys_ < 80:
            noter(12, f"tension très basse ({sys_})", 1)
        elif sys_ >= 180 or sys_ < 90:
            noter(8, f"tension anormale ({sys_})")
        elif sys_ >= 160 or sys_ < 100:
            noter(4, f"tension inhabituelle ({sys_})")

    return points, minimal, notes


def _evaluer_echelles(auto, temperature_mesuree=False):
    """Renvoie (points, niveau_minimal ou None, [messages]) pour l'auto-évaluation.

    Si la température a été mesurée, elle remplace l'échelle de fièvre
    (sinon la fièvre serait comptée deux fois)."""
    points, minimal, notes = 0, None, []
    for nom, table in POINTS_ECHELLES.items():
        if nom == "fievre" and temperature_mesuree:
            continue
        try:
            valeur = int(auto.get(nom) or 0)
        except (TypeError, ValueError):
            continue
        valeur = max(0, min(NIVEAU_MAX, valeur))
        pts, niveau_min = table[valeur]
        points += pts
        if niveau_min is not None:
            minimal = niveau_min if minimal is None else min(minimal, niveau_min)
        if valeur >= 2:  # les valeurs 0 et 1 ne méritent pas d'être citées
            notes.append(
                f"{ECHELLES[nom]['court']} : {libelle(nom, valeur).lower()} ({valeur}/{NIVEAU_MAX})"
            )
    return points, minimal, notes


def evaluer(symptomes, constantes=None, auto_evaluation=None):
    """Évalue l'urgence.

    symptomes : liste de dicts {nom, poids, drapeau_rouge, niveau_minimal}.
    constantes : dict facultatif (temperature, saturation_oxygene,
        frequence_cardiaque, tension_systolique) ; valeurs None ignorées.
    auto_evaluation : dict facultatif {douleur, fievre, respiration, etat_general}
        avec des valeurs de 0 à 5 données par le patient.
    """
    score = sum(int(s.get("poids") or 0) for s in symptomes)
    niveaux_minimaux = []
    raisons = []
    drapeaux = []

    for s in symptomes:
        if s.get("drapeau_rouge"):
            drapeaux.append(s["nom"])
            niveaux_minimaux.append(
                s.get("niveau_minimal") or NIVEAU_DRAPEAU_ROUGE_PAR_DEFAUT
            )

    if drapeaux:
        raisons.append("signe d'alerte déclaré : " + ", ".join(drapeaux))
    elif symptomes:
        raisons.append(f"{len(symptomes)} symptôme(s) déclaré(s)")

    pts, minimal_constantes, notes = _evaluer_constantes(constantes or {})
    score += pts
    raisons.extend(notes)
    if minimal_constantes is not None:
        niveaux_minimaux.append(minimal_constantes)

    pts_e, minimal_e, notes_e = _evaluer_echelles(
        auto_evaluation or {},
        temperature_mesuree=(constantes or {}).get("temperature") is not None,
    )
    score += pts_e
    raisons.extend(notes_e)
    if minimal_e is not None:
        niveaux_minimaux.append(minimal_e)

    niveau = _niveau_depuis_score(score)
    if niveaux_minimaux:
        niveau = min(niveau, min(niveaux_minimaux))

    if not raisons:
        raisons.append("aucun symptôme précis déclaré")
    explication = f"Niveau {niveau} (score {score}) : " + " ; ".join(raisons) + "."
    return Resultat(score=score, niveau=niveau, explication=explication, drapeaux_rouges=drapeaux)


MESSAGES_NIVEAU = {
    1: "Situation potentiellement vitale : appelez immédiatement les urgences (190 / 15 / 112).",
    2: "Très urgent : votre demande est placée en tête de la file du médecin.",
    3: "Urgent : une consultation est recommandée dans l'heure.",
    4: "Standard : votre demande est placée dans la file normale.",
    5: "Non urgent : le médecin vous répondra dans l'ordre d'arrivée.",
}
