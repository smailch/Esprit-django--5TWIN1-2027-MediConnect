"""Analyse par règles du compte rendu de soin (logique pure, sans base ni IA).

1. extraire_constantes : repère dans la note de l'infirmier « T 38,4 », « TA 15/9 », « pouls 98 », « sat 93 % » ;
2. signes_du_texte     : repère les signes d'alerte du catalogue (« plaie rouge », « essoufflée »…), sauf s'ils sont niés ;
3. signes_des_constantes : compare les constantes aux seuils des mesures de santé (Mesure.REGLES) ;
4. signes_d_evolution  : repère une constante qui se dégrade d'un passage à l'autre ;
5. niveau              : RAS, à surveiller ou à signaler au médecin.

Ces règles fonctionnent toujours ; l'IA (ia_soin.py) ne fait que compléter ce qu'elles n'ont pas reconnu.
Ce sont des repères pour attirer l'attention, pas un diagnostic : les seuils sont à faire valider par un soignant.
"""
import re
from dataclasses import dataclass

from patients.analyse_dossier import normaliser
from patients.ia_garde_fous import citation_niee
from patients.models import Mesure

RAS, SURVEILLER, SIGNALER = "ras", "surveiller", "signaler"  # mêmes valeurs que models.NiveauAlerte
RANG = {RAS: 0, SURVEILLER: 1, SIGNALER: 2}
LIBELLES = {RAS: "RAS", SURVEILLER: "À surveiller", SIGNALER: "À signaler au médecin"}
TEXTE, IA, CONSTANTES, EVOLUTION = "texte", "ia", "constantes", "evolution"

CONSTANTES_SUIVIES = ("temperature", "tension_systolique", "tension_diastolique", "frequence_cardiaque", "saturation_oxygene")
UNITES = {
    "temperature": "°C", "tension_systolique": "mmHg", "tension_diastolique": "mmHg",
    "frequence_cardiaque": "/min", "saturation_oxygene": "%",
}
# Bornes plausibles : reprises des mesures de santé du patient, pour que les deux parlent la même langue.
BORNES = {
    "temperature": Mesure.REGLES["temperature"][1:3],
    "tension_systolique": Mesure.REGLES["tension"][1:3],
    "tension_diastolique": Mesure.DIASTOLE[:2],
    "frequence_cardiaque": Mesure.REGLES["frequence"][1:3],
    "saturation_oxygene": Mesure.REGLES["saturation"][1:3],
}


@dataclass(frozen=True)
class Signe:
    nom: str
    extrait: str
    gravite: str
    origine: str


# --- 1. constantes écrites dans la note --------------------------------------------------------------------

_LIAISON = r"\s*(?:[:=]|à|a|de)?\s*"
_MOTIFS = {
    "temperature": [
        re.compile(r"(?<!\w)(?:t°?|temp(?:[ée]rature)?\.?)" + _LIAISON + r"(\d{2}(?:[.,]\d)?)(?:\s*°\s*c?)?(?![\d/])", re.I),
        re.compile(r"(?<![\d.,])(\d{2}[.,]\d)\s*°\s*c?", re.I),
    ],
    "tension": [
        re.compile(r"(?<!\w)(?:ta|pa|tension(?:\s+art[ée]rielle)?)" + _LIAISON + r"(\d{2,3})\s*[/x]\s*(\d{1,3})(?!\d)", re.I),
    ],
    "frequence_cardiaque": [
        re.compile(r"(?<!\w)(?:pouls|fc|fr[ée]quence\s+cardiaque)" + _LIAISON + r"(\d{2,3})(?!\d)", re.I),
        re.compile(r"(?<![\d.,])(\d{2,3})\s*(?:bpm|battements?\s*(?:/|par)\s*min)", re.I),
    ],
    "saturation_oxygene": [
        re.compile(r"(?<!\w)(?:sat(?:uration)?(?:\s+en\s+(?:o2|oxyg[èe]ne))?|spo2|sp02)" + _LIAISON + r"(\d{2,3})(?!\d)\s*%?", re.I),
    ],
}


def _nombre(texte):
    return float(texte.replace(",", "."))


def _plausible(nom, valeur):
    mini, maxi = BORNES[nom]
    return mini <= valeur <= maxi


def tension_en_mmhg(haute, basse):
    """« 15/9 » s'écrit en centimètres de mercure : on le ramène en mmHg (150/90)."""
    if haute < 30:
        return haute * 10, basse * 10
    return haute, basse


def extraire_constantes(texte):
    """{nom: (valeur, extrait)} pour chaque constante trouvée (la première occurrence plausible)."""
    trouvees = {}
    texte = texte or ""
    for nom, motifs in _MOTIFS.items():
        for motif in motifs:
            for m in motif.finditer(texte):
                extrait = " ".join(m.group(0).split())
                if nom == "tension":
                    haute, basse = tension_en_mmhg(_nombre(m.group(1)), _nombre(m.group(2)))
                    if _plausible("tension_systolique", haute) and _plausible("tension_diastolique", basse) and basse < haute:
                        trouvees.setdefault("tension_systolique", (haute, extrait))
                        trouvees.setdefault("tension_diastolique", (basse, extrait))
                        break
                else:
                    valeur = _nombre(m.group(1))
                    if _plausible(nom, valeur):
                        trouvees.setdefault(nom, (valeur, extrait))
                        break
            if nom in trouvees or (nom == "tension" and "tension_systolique" in trouvees):
                break
    return trouvees


# --- 2. signes d'alerte du texte ----------------------------------------------------------------------------
# nom affiché -> (gravité, expressions écrites sans accents ni majuscules, comparées mot à mot)

CATALOGUE = {
    "Signes d'infection de la plaie": (SIGNALER, (
        "plaie rouge", "plaie chaude", "plaie inflammatoire", "plaie infectee", "plaie malodorante", "rougeur", "rougeurs",
        "rouge et chaude", "rouge et chaud", "rouge et gonflee", "rougeatre",
        "enflamme", "enflammee", "enflammes", "enflammees", "chaud et rouge", "chaude et rouge",
        "inflammation", "pus", "purulent", "purulente", "ecoulement purulent", "mauvaise odeur", "suintement",
    )),
    "Difficulté respiratoire": (SIGNALER, (
        "essouffle", "essoufflee", "essoufflement", "dyspnee", "respire mal", "gene respiratoire",
        "difficulte a respirer", "difficultes a respirer", "difficultes respiratoires",
    )),
    "Confusion ou somnolence": (SIGNALER, (
        "confus", "confuse", "confusion", "desoriente", "desorientee", "somnolent", "somnolente", "ne reconnait pas",
    )),
    "Saignement": (SIGNALER, ("saignement", "saigne", "saignait", "hemorragie", "sang dans")),
    "Malaise": (SIGNALER, ("malaise", "perte de connaissance", "evanoui", "evanouie", "syncope")),
    "Douleur thoracique": (SIGNALER, ("douleur thoracique", "douleur dans la poitrine", "oppression thoracique")),
    "Fièvre": (SURVEILLER, ("fievre", "febrile", "frissons", "frissonne")),  # même nom que le seuil de température : fusionnés
    "Douleur importante": (SURVEILLER, (
        "douleur intense", "douleur forte", "douleur importante", "tres douloureux", "tres douloureuse",
        "eva 7", "eva 8", "eva 9", "eva 10",
    )),
    "Œdème": (SURVEILLER, ("oedeme", "oedemes", "gonflement", "gonfle", "gonflee", "jambes gonflees", "jambe gonflee")),
    "Chute": (SURVEILLER, ("chute", "est tombe", "est tombee", "tombe par terre", "tombee par terre")),
    "Traitement non pris": (SURVEILLER, (
        "n a pas pris", "oubli de traitement", "oublie son traitement", "refuse le traitement", "refuse son traitement",
        "refus de soin", "refuse le soin",
    )),
    "Perte d'appétit ou déshydratation": (SURVEILLER, (
        "ne mange plus", "ne boit plus", "deshydrate", "deshydratee", "perte d appetit", "mange tres peu",
    )),
}

_MOT = re.compile(r"\w+")


def _mots(texte):
    """[(début, fin, mot normalisé)] : garde la position de chaque mot pour citer le texte d'origine."""
    return [(m.start(), m.end(), normaliser(m.group().replace("œ", "oe").replace("Œ", "Oe"))) for m in _MOT.finditer(texte or "")]


def _chercher(texte, mots, expression):
    """Extrait du texte d'origine qui correspond à l'expression, ou None."""
    cible = expression.split()
    n = len(cible)
    for i in range(len(mots) - n + 1):
        if [m[2] for m in mots[i:i + n]] == cible:
            return texte[mots[i][0]:mots[i + n - 1][1]]
    return None


def signes_du_texte(texte):
    """Signes du catalogue présents dans la note (une seule fois chacun), sauf s'ils sont niés : « pas de rougeur »."""
    texte = texte or ""
    mots = _mots(texte)
    signes = []
    for nom, (gravite, expressions) in CATALOGUE.items():
        for expression in expressions:
            extrait = _chercher(texte, mots, expression)
            if extrait and not citation_niee(texte, extrait):
                signes.append(Signe(nom, extrait, gravite, TEXTE))
                break
    return signes


# --- 3. seuils des constantes -------------------------------------------------------------------------------------
# (nom, gravité, condition, libellé) ; la première condition vraie l'emporte pour chaque constante.

SEUILS = {
    "temperature": (
        (SIGNALER, lambda v: v >= 39.5, "Fièvre élevée"),
        (SIGNALER, lambda v: v < 35.5, "Température basse"),
        (SURVEILLER, lambda v: v >= Mesure.REGLES["temperature"][4], "Fièvre"),
    ),
    "tension_systolique": (
        (SIGNALER, lambda v: v >= 180, "Tension très élevée"),
        (SIGNALER, lambda v: v < Mesure.REGLES["tension"][3], "Tension basse"),
        (SURVEILLER, lambda v: v >= Mesure.REGLES["tension"][4], "Tension élevée"),
    ),
    "tension_diastolique": (
        (SIGNALER, lambda v: v >= 110, "Tension très élevée"),
        (SURVEILLER, lambda v: v >= Mesure.DIASTOLE[3], "Tension élevée"),
    ),
    "frequence_cardiaque": (
        (SIGNALER, lambda v: v > 120 or v < 45, "Pouls anormal"),
        (SURVEILLER, lambda v: v >= Mesure.REGLES["frequence"][4] or v < Mesure.REGLES["frequence"][3], "Pouls à surveiller"),
    ),
    "saturation_oxygene": (
        (SIGNALER, lambda v: v < 90, "Saturation basse"),
        (SURVEILLER, lambda v: v < Mesure.REGLES["saturation"][3], "Saturation à surveiller"),
    ),
}


def _format(valeur):
    return f"{valeur:g}".replace(".", ",")


def signes_des_constantes(constantes, extraits=None):
    """constantes : {nom: valeur} ; extraits : {nom: extrait de la note} pour justifier le signe.
    La tension ne produit qu'un signe (le plus grave des deux chiffres)."""
    extraits = extraits or {}
    signes = {}
    for nom, regles in SEUILS.items():
        valeur = constantes.get(nom)
        if valeur is None:
            continue
        for gravite, condition, libelle in regles:
            if condition(float(valeur)):
                if nom.startswith("tension"):
                    haute, basse = constantes.get("tension_systolique"), constantes.get("tension_diastolique")
                    preuve = extraits.get(nom) or f"TA {_format(haute)}/{_format(basse)} mmHg"
                    cle = "tension"
                else:
                    preuve = extraits.get(nom) or f"{_format(float(valeur))} {UNITES[nom]}"
                    cle = nom
                ancien = signes.get(cle)
                if ancien is None or RANG[gravite] > RANG[ancien.gravite]:
                    signes[cle] = Signe(libelle, preuve, gravite, CONSTANTES)
                break
    return list(signes.values())


# --- 4. évolution d'un passage à l'autre ------------------------------------------------------------------------
# constante -> (sens de la dégradation, seuil à partir duquel on la signale, libellé)

DEGRADATIONS = {
    "tension_systolique": (+1, Mesure.REGLES["tension"][4], "Tension en hausse"),
    "temperature": (+1, Mesure.REGLES["temperature"][4], "Température en hausse"),
    "frequence_cardiaque": (+1, Mesure.REGLES["frequence"][4], "Pouls en hausse"),
    "saturation_oxygene": (-1, Mesure.REGLES["saturation"][3], "Saturation en baisse"),
}
PASSAGES_EVOLUTION = 3  # la valeur actuelle et les deux précédentes


def signes_d_evolution(historique, constantes):
    """historique : [{nom: valeur}] du plus ancien au plus récent (passages ou mesures précédents).
    Signale une constante qui se dégrade à chaque fois sur les 3 dernières valeurs et dépasse son seuil."""
    signes = []
    for nom, (sens, seuil, libelle) in DEGRADATIONS.items():
        actuelle = constantes.get(nom)
        if actuelle is None:
            continue
        valeurs = [float(h[nom]) for h in historique if h.get(nom) is not None][-(PASSAGES_EVOLUTION - 1):] + [float(actuelle)]
        if len(valeurs) < PASSAGES_EVOLUTION:
            continue
        se_degrade = all((b - a) * sens > 0 for a, b in zip(valeurs, valeurs[1:]))
        depasse = actuelle >= seuil if sens > 0 else actuelle < seuil
        if se_degrade and depasse:
            suite = " → ".join(_format(v) for v in valeurs)
            signes.append(Signe(libelle, f"{suite} {UNITES[nom]} sur les {len(valeurs)} derniers relevés", SURVEILLER, EVOLUTION))
    return signes


# --- 5. niveau ---------------------------------------------------------------------------------------------------


def niveau(signes):
    return max((s.gravite for s in signes), key=RANG.__getitem__, default=RAS)


def fusionner(*listes):
    """Un seul signe par nom : le premier rencontré (règles avant IA), ou le plus grave s'ils diffèrent."""
    retenus = {}
    for liste in listes:
        for signe in liste:
            ancien = retenus.get(signe.nom)
            if ancien is None or RANG[signe.gravite] > RANG[ancien.gravite]:
                retenus[signe.nom] = signe
    return sorted(retenus.values(), key=lambda s: -RANG[s.gravite])
