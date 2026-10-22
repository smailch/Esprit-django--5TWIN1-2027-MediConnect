"""Garde-fous de l'IA (logique pure) : on ne fait jamais confiance à la sortie d'un modèle de langage.

* anonymisation avant envoi (e-mails, téléphones, adresses web) et limite de longueur ;
* chaque détection doit citer un extrait du texte du patient, et cet extrait est vérifié mot pour mot ;
* une détection niée (« pas de fièvre ») ou concernant un proche est écartée, même si le modèle la propose ;
* seules les valeurs des listes autorisées sont acceptées ;
* une reformulation est refusée si elle contient un chiffre ou un médicament absent des données d'entrée.
"""
import re

from .analyse_dossier import FAMILLE_PROCHE, FAMILLES, MEDICAMENTS, NEGATIONS, normaliser

LONGUEUR_MAX_ENVOI = 1500
EXTRAIT_MIN, EXTRAIT_MAX = 3, 160
MAX_DETECTIONS = 8
LONGUEUR_MAX_REFORMULATION = 900  # un résumé de tout le dossier : cinq phrases
NUMEROS_URGENCE = {"190", "15", "112"}  # toujours autorisés dans un texte destiné au patient

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_TELEPHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .\-/]{6,}\d)(?!\w)")


def anonymiser(texte, limite=LONGUEUR_MAX_ENVOI):
    """Retire ce qui identifie directement (e-mail, téléphone, lien), puis tronque."""
    texte = _EMAIL.sub("[e-mail]", texte or "")
    texte = _URL.sub("[lien]", texte)
    texte = _TELEPHONE.sub("[numéro]", texte)
    return re.sub(r"[ \t]+", " ", texte).strip()[:limite]


def tranche_age(age):
    """30 -> « 30-39 ans » : on n'envoie jamais la date de naissance."""
    if age is None or age < 0:
        return "âge inconnu"
    if age < 18:
        return "moins de 18 ans"
    debut = (age // 10) * 10
    return f"{debut}-{debut + 9} ans"


def citation_valide(extrait, texte):
    """L'extrait cité par le modèle figure-t-il bien, mot pour mot (hors accents et casse), dans le texte ?"""
    e, t = normaliser(extrait), normaliser(texte)
    if not (EXTRAIT_MIN <= len(e) <= EXTRAIT_MAX):
        return False
    return f" {e} " in f" {t} "


def citation_niee(texte, extrait):
    """La citation est-elle niée ou concerne-t-elle un proche ?

    Trois contrôles : la citation contient un mot de parenté (« mon père est diabétique »), commence par une
    négation (« pas de fièvre »), ou l'un de ces mots se trouve dans les 3 mots qui la précèdent, dans sa proposition.
    Une négation au milieu d'une citation n'est pas écartée : « je n'arrive plus à respirer » est un vrai signal
    d'alerte. Pour ce cas ambigu, on préfère un excès de prudence (le médecin voit la citation et peut requalifier)."""
    e = normaliser(extrait)
    mots = e.split()
    if set(mots) & FAMILLE_PROCHE or (mots and mots[0] in NEGATIONS):
        return True
    for segment in re.split(r"[.;,\n]+", texte or ""):
        s = normaliser(segment)
        position = f" {s} ".find(f" {e} ")
        if position >= 0:
            avant = f" {s} "[:position].split()[-3:]
            if (NEGATIONS | FAMILLE_PROCHE) & set(avant):
                return True
    return False


def valider_detections(brut, autorises, texte, *, maximum=MAX_DETECTIONS, unique=True):
    """Garde les détections valides d'une réponse de modèle.

    brut      : liste de {"nom": …, "extrait": …} (n'importe quoi d'autre est ignoré) ;
    autorises : {valeur normalisée: valeur canonique} (liste blanche) ;
    texte     : texte du patient dont l'extrait doit être tiré ;
    unique    : un seul résultat par nom (False : une même famille peut concerner plusieurs allergies).
    Renvoie [(nom canonique, extrait)] sans doublon, dans l'ordre."""
    retenues, vus = [], set()
    if not isinstance(brut, list):
        return retenues
    for element in brut:
        if not isinstance(element, dict):
            continue
        nom, extrait = element.get("nom"), element.get("extrait")
        if not isinstance(nom, str) or not isinstance(extrait, str):
            continue
        canonique = autorises.get(normaliser(nom))
        cle = canonique if unique else (canonique, normaliser(extrait))
        if canonique is None or cle in vus:
            continue
        if not citation_valide(extrait, texte) or citation_niee(texte, extrait):
            continue
        vus.add(cle)
        retenues.append((canonique, " ".join(extrait.split())))
        if len(retenues) >= maximum:
            break
    return retenues


def liste_blanche(noms):
    return {normaliser(n): n for n in noms}


# --- reformulation ------------------------------------------------------------------------------------


def _nombres(texte):
    return set(re.findall(r"\d+(?:[.,]\d+)?", (texte or "").replace(",", ".")))


def _termes_medicaux():
    termes = set()
    for _, liste in FAMILLES.values():
        termes.update(liste)
    for liste, _, _ in MEDICAMENTS.values():
        termes.update(liste)
    return {t for t in termes if len(t) >= 5}


def reformulation_valide(sortie, entree):
    """Texte de reformulation accepté, ou None. Refuse tout chiffre ou médicament absent de l'entrée,
    les liens, les textes trop longs ou vides."""
    if not isinstance(sortie, str):
        return None
    sortie = " ".join(sortie.split())
    if not sortie or len(sortie) > LONGUEUR_MAX_REFORMULATION or _URL.search(sortie) or _EMAIL.search(sortie):
        return None
    if not _nombres(sortie) <= _nombres(entree) | NUMEROS_URGENCE:
        return None  # un chiffre inventé (dose, valeur de mesure…)
    entree_n, sortie_n = f" {normaliser(entree)} ", f" {normaliser(sortie)} "
    for terme in _termes_medicaux():
        if f" {terme} " in sortie_n and f" {terme} " not in entree_n:
            return None  # un médicament que l'analyse n'a pas cité
    return sortie
