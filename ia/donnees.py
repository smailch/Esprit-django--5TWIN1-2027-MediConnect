"""Fabrique le jeu de données d'entraînement (et d'évaluation) du modèle de lecture du texte.

Aucune donnée de vrais patients n'existe dans le projet : les phrases sont GÉNÉRÉES à partir du lexique
(lexique.py), avec du « bruit » (fautes de frappe, accents oubliés, formules de politesse, négations, proches).
Le niveau d'urgence de chaque phrase n'est pas inventé : il est calculé par le moteur de règles du projet
(patients.triage.evaluer) à partir de ce que la phrase déclare. Le modèle apprend donc à lire du texte libre comme
les règles lisent les cases cochées. C'est un jeu SYNTHÉTIQUE : il faudrait des données cliniques validées pour un
usage réel.
"""
import random
import unicodedata

from patients.triage import evaluer

from . import lexique as lx


def catalogue():
    """Le catalogue de symptômes du projet : {nom: dict utilisable par evaluer()}."""
    from patients.management.commands.charger_symptomes import SYMPTOMES

    return {
        nom: {"nom": nom, "poids": poids, "drapeau_rouge": rouge, "niveau_minimal": minimal}
        for nom, poids, rouge, minimal in SYMPTOMES
    }


def niveau_des_effets(effets, symptomes_du_catalogue=None):
    """Niveau d'urgence (1 à 5) calculé par les règles pour une liste d'effets (voir lexique.UNITES)."""
    cat = symptomes_du_catalogue or catalogue()
    symptomes, auto, temperature = {}, {}, None
    for effet in effets:
        for cle in ("symptome", "symptome2"):
            if cle in effet:
                symptomes[effet[cle]] = cat[effet[cle]]
        if "echelle" in effet:
            nom, valeur = effet["echelle"]
            auto[nom] = max(auto.get(nom, 0), valeur)
        if effet.get("temperature") is not None:
            temperature = max(temperature or 0, effet["temperature"])
    constantes = {"temperature": temperature} if temperature is not None else {}
    return evaluer(list(symptomes.values()), constantes, auto).niveau


def _sans_accents(texte):
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def _faute_de_frappe(texte, rng):
    mots = texte.split(" ")
    candidats = [i for i, m in enumerate(mots) if len(m) > 4 and m.isalpha()]
    if not candidats:
        return texte
    i = rng.choice(candidats)
    m, k = mots[i], rng.randrange(1, len(mots[i]) - 2)
    mots[i] = m[:k] + m[k + 1] + m[k] + m[k + 2:]  # deux lettres voisines échangées
    return " ".join(mots)


def _bruiter(texte, rng):
    if rng.random() < 0.40:
        texte = texte.lower()
    if rng.random() < 0.25:
        texte = _sans_accents(texte)
    if rng.random() < 0.15:
        texte = _faute_de_frappe(texte, rng)
    return texte


def _forme(unite, rng):
    """(texte, effet) d'une unité : les unités « température » prennent une valeur au hasard."""
    effet = dict(unite["effet"])
    forme = rng.choice(unite["formes"])
    if "valeurs" in unite:
        t = rng.choice(unite["valeurs"])
        effet["temperature"] = t
        forme = forme.format(t=str(t).replace(".", ","))
    return forme, effet


def _poids(unites):
    return [u["poids"] for u in unites]


def phrase(rng, symptomes_du_catalogue=None):
    """Une phrase de patient et son niveau d'urgence : (texte, niveau, effets)."""
    unites = lx.UNITES
    sans_effet = [u for u in unites if not u["effet"]]
    avec_effet = [u for u in unites if u["effet"]]
    k = rng.choices([0, 1, 2, 3, 4], weights=[8, 34, 30, 18, 10])[0]
    morceaux, effets = [], []
    if k == 0:
        forme, _ = _forme(rng.choice(sans_effet), rng)
        morceaux.append(forme)
    else:
        choisies = []
        while len(choisies) < k:
            u = rng.choices(avec_effet, weights=_poids(avec_effet))[0]
            if u not in choisies:
                choisies.append(u)
        for u in choisies:
            forme, effet = _forme(u, rng)
            morceaux.append(forme)
            effets.append(effet)
    if rng.random() < 0.20:
        morceaux.append(rng.choice(lx.NEGATIONS).format(x=rng.choice(lx.NOMS_NIES)))
    if rng.random() < 0.12:
        morceaux.append(rng.choice(lx.FORMES_PROCHES).format(p=rng.choice(lx.PROCHES), x=rng.choice(lx.NOMS_PROCHES)))
    if rng.random() < 0.05:
        morceaux.append(rng.choice(lx.PASSE).format(x=rng.choice(lx.NOMS_PROCHES)))
    rng.shuffle(morceaux)
    texte = morceaux[0] + rng.choice(lx.DUREES)
    for m in morceaux[1:]:
        texte += rng.choice(lx.LIAISONS) + m
    texte = rng.choice(lx.DEBUTS) + texte + rng.choice(lx.FINS)
    texte = _bruiter(texte, rng)
    return texte, niveau_des_effets(effets, symptomes_du_catalogue), effets


def generer(n, graine=1):
    """n phrases [(texte, niveau)], toujours les mêmes pour une même graine."""
    rng, cat = random.Random(graine), catalogue()
    sortie = []
    for _ in range(n):
        texte, niveau, _ = phrase(rng, cat)
        sortie.append((texte, niveau))
    return sortie


# --- Phrases écrites à la main : un contrôle HORS du lexique -------------------------------------------------
# (texte, effets déclarés). Le niveau attendu est calculé par les règles, comme pour le jeu généré.
S = lambda nom: {"symptome": nom}  # noqa: E731
E = lambda nom, v: {"echelle": (nom, v)}  # noqa: E731
T = lambda t: {"temperature": t}  # noqa: E731

PHRASES_A_LA_MAIN = [
    ("Une douleur très forte me serre la poitrine depuis une heure et irradie dans le bras gauche", [S("Douleur thoracique")]),
    ("Mon fils a perdu connaissance et il convulse", [S("Perte de connaissance"), S("Convulsions")]),
    ("Je saigne beaucoup et je n'arrive pas à arrêter le saignement", [S("Saignement abondant")]),
    ("Mon visage est paralysé d'un côté et je parle mal depuis une heure", [S("Paralysie ou trouble de la parole")]),
    ("Réaction allergique : mon visage gonfle et ma gorge se ferme", [S("Difficulté à respirer")]),
    ("J'ai une forte fièvre à 40 depuis hier et je suis très confus", [T(40), E("etat_general", 5)]),
    ("Mal de ventre très violent depuis ce matin, je vomis sans arrêt", [S("Douleur abdominale intense"), S("Vomissements")]),
    ("Il fait une crise d'épilepsie depuis cinq minutes", [S("Convulsions")]),
    ("Je me suis évanoui dans la rue et j'ai très mal à la tête", [S("Perte de connaissance"), S("Maux de tête")]),
    ("Je suffoque, je ne peux plus dire une phrase sans reprendre mon souffle", [S("Difficulté à respirer"), E("respiration", 5)]),
    ("Douleur atroce dans le ventre, je ne peux plus me redresser", [S("Douleur abdominale intense")]),
    ("Oppression dans la poitrine quand je monte les escaliers", [S("Douleur thoracique")]),
    ("J'ai de la fièvre à 38,5 depuis deux jours et je tousse", [T(38.5), S("Toux")]),
    ("Je me sens très faible, à bout de forces, et j'ai une fièvre à 39", [E("etat_general", 4), T(39)]),
    ("Éruption cutanée avec forte fièvre et je suis très faible", [S("Éruption cutanée"), E("fievre", 4), E("etat_general", 4)]),
    ("Fièvre et toux grasse, mal à la gorge, courbatures et très fatigué", [E("fievre", 3), S("Toux"), S("Mal de gorge"), S("Douleur musculaire ou articulaire"), S("Fatigue")]),
    ("Je vomis depuis hier soir et j'ai la diarrhée, je n'arrive plus à rien boire", [S("Vomissements"), S("Diarrhée")]),
    ("Migraine terrible avec vomissements", [S("Maux de tête"), S("Vomissements")]),
    ("J'ai une douleur insupportable au dos depuis ce matin", [S("Douleur musculaire ou articulaire"), E("douleur", 5)]),
    ("Je suis essoufflé et j'ai du mal à respirer depuis hier", [E("respiration", 3)]),
    ("Je me suis fait une entorse à la cheville, ça gonfle beaucoup", [S("Douleur musculaire ou articulaire"), E("douleur", 3)]),
    ("J'ai mal au ventre et la diarrhée depuis ce matin", [S("Douleur abdominale"), S("Diarrhée")]),
    ("Mal de gorge et nez qui coule depuis trois jours", [S("Mal de gorge")]),
    ("J'ai des plaques rouges qui grattent sur les bras", [S("Éruption cutanée")]),
    ("Vertiges quand je me lève, je suis tombé ce matin", [S("Vertiges")]),
    ("Mal de tête depuis ce matin", [S("Maux de tête")]),
    ("Douleur au genou depuis une semaine", [S("Douleur musculaire ou articulaire")]),
    ("Je tousse un peu la nuit, c'est tout", [S("Toux")]),
    ("Petit rhume sans fièvre, juste un peu fatigué", [S("Fatigue")]),
    ("Pas de perte de connaissance, juste un peu de vertiges", [S("Vertiges")]),
    ("Je voudrais renouveler mon ordonnance de tension", []),
    ("Je veux un certificat médical pour le sport", []),
    ("Pas de fièvre, pas de toux, tout va bien, simple contrôle", []),
    ("Mon père a eu une douleur à la poitrine hier, moi je vais bien", []),
    ("Je n'ai aucune difficulté à respirer, je veux juste un bilan", []),
    ("Ma mère a eu une crise de convulsions la semaine dernière, moi je vais très bien", []),
    ("Rien de grave, juste une visite de contrôle pour ma fille", []),
    ("Aucune douleur, aucune fièvre, je veux juste une ordonnance", []),
    ("Bonjour, je souhaite prendre rendez-vous pour mon suivi de routine", []),
]


def phrases_a_la_main():
    """[(texte, niveau)] des phrases écrites à la main."""
    cat = catalogue()
    return [(texte, niveau_des_effets(effets, cat)) for texte, effets in PHRASES_A_LA_MAIN]
