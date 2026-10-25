"""Phrases de patients, en français courant, pour fabriquer le jeu de données du modèle (voir donnees.py).

Chaque « unité » est une façon de dire une chose, avec son EFFET sur le triage : le symptôme du catalogue qu'elle
déclare, une valeur d'échelle d'auto-évaluation (douleur, fièvre, respiration, état général) ou une température.
Le niveau d'urgence d'une phrase est ensuite calculé par le moteur de règles du projet (patients.triage.evaluer) à
partir de ces effets : le modèle apprend donc à lire du texte comme les règles lisent les cases cochées.

Ce sont des phrases écrites pour la démonstration, pas des propos de vrais patients.
"""

# effet : {"symptome": nom du catalogue} | {"echelle": (nom, valeur 0 à 5)} | {"temperature": degrés} | {} (aucun effet)
# poids : fréquence relative dans le jeu de données (les cas courants sont plus fréquents que les cas graves)
UNITES = [
    # --- signes d'alerte (symptômes du catalogue marqués « drapeau rouge ») ------------------------------------
    {"effet": {"symptome": "Douleur thoracique"}, "poids": 3, "formes": [
        "j'ai une douleur dans la poitrine", "ça me serre la poitrine", "j'ai très mal au thorax",
        "une douleur serre ma poitrine et irradie dans le bras gauche", "j'ai une oppression dans la poitrine",
        "j'ai comme un poids sur la poitrine", "douleur thoracique forte", "mon coeur me fait mal et ça serre"]},
    {"effet": {"symptome": "Difficulté à respirer", "echelle": ("respiration", 5)}, "poids": 3, "formes": [
        "je n'arrive plus à respirer", "je suffoque", "je manque d'air et mes lèvres deviennent bleues",
        "je m'étouffe, je n'ai plus d'air", "difficulté très importante à respirer", "j'étouffe, je ne peux plus parler tellement je manque d'air"]},
    {"effet": {"symptome": "Perte de connaissance"}, "poids": 2, "formes": [
        "j'ai perdu connaissance", "je me suis évanoui ce matin", "je suis tombé dans les pommes",
        "j'ai fait un malaise avec perte de connaissance", "elle a perdu connaissance quelques secondes"]},
    {"effet": {"symptome": "Saignement abondant"}, "poids": 2, "formes": [
        "je saigne beaucoup", "le saignement ne s'arrête pas", "j'ai une hémorragie", "ça saigne abondamment et je n'arrive pas à arrêter",
        "je perds beaucoup de sang"]},
    {"effet": {"symptome": "Paralysie ou trouble de la parole"}, "poids": 2, "formes": [
        "mon visage est paralysé d'un côté", "je n'arrive plus à bouger le bras droit", "je parle de travers et je cherche mes mots",
        "j'ai un trouble soudain de la parole", "ma bouche est tordue et mon bras est engourdi", "je n'arrive plus à articuler"]},
    {"effet": {"symptome": "Convulsions"}, "poids": 2, "formes": [
        "j'ai des convulsions", "il fait une crise de convulsions", "j'ai fait une crise d'épilepsie", "elle convulse depuis quelques minutes"]},
    {"effet": {"symptome": "Douleur abdominale intense"}, "poids": 3, "formes": [
        "j'ai une douleur au ventre insupportable", "mal au ventre très violent", "le ventre dur et très douloureux",
        "une douleur abdominale intense qui ne passe pas", "j'ai atrocement mal au ventre"]},
    # --- symptômes courants ---------------------------------------------------------------------------------------
    {"effet": {"symptome": "Toux"}, "poids": 9, "formes": [
        "je tousse", "j'ai une toux sèche", "une toux grasse qui ne passe pas", "je tousse beaucoup la nuit", "toux persistante"]},
    {"effet": {"symptome": "Mal de gorge"}, "poids": 8, "formes": [
        "j'ai mal à la gorge", "la gorge qui gratte et qui brûle", "une angine", "mal de gorge en avalant", "ma gorge est irritée"]},
    {"effet": {"symptome": "Maux de tête"}, "poids": 8, "formes": [
        "j'ai mal à la tête", "une migraine", "mal de tête depuis ce matin", "la tête qui tape fort", "maux de tête fréquents"]},
    {"effet": {"symptome": "Vomissements"}, "poids": 5, "formes": [
        "je vomis", "j'ai des vomissements", "nausées et vomissements", "j'ai vomi plusieurs fois", "je n'arrête pas de vomir"]},
    {"effet": {"symptome": "Diarrhée"}, "poids": 5, "formes": [
        "j'ai la diarrhée", "des selles liquides", "diarrhée depuis plusieurs heures", "je vais très souvent aux toilettes"]},
    {"effet": {"symptome": "Douleur abdominale"}, "poids": 6, "formes": [
        "j'ai mal au ventre", "des douleurs d'estomac", "des crampes au ventre", "le ventre qui fait mal par moments"]},
    {"effet": {"symptome": "Vertiges"}, "poids": 5, "formes": [
        "j'ai des vertiges", "la tête qui tourne quand je me lève", "des étourdissements", "j'ai le vertige et je suis instable"]},
    {"effet": {"symptome": "Éruption cutanée"}, "poids": 5, "formes": [
        "j'ai des plaques rouges qui grattent", "des boutons sur les bras", "une éruption sur la peau", "la peau rouge et qui démange"]},
    {"effet": {"symptome": "Fatigue"}, "poids": 7, "formes": [
        "je suis très fatigué", "épuisé depuis quelques jours", "je n'ai plus d'énergie", "grosse fatigue", "je suis fatiguée tout le temps"]},
    {"effet": {"symptome": "Douleur musculaire ou articulaire"}, "poids": 7, "formes": [
        "j'ai mal au dos", "douleur au genou", "des courbatures partout", "mal aux articulations", "une douleur à l'épaule", "j'ai mal à la cheville"]},
    # --- ce que le patient exprime avec une intensité (échelles d'auto-évaluation) ----------------------------------
    {"effet": {"echelle": ("fievre", 1)}, "poids": 4, "formes": ["j'ai un peu de température", "je me sens un peu chaud", "petite fièvre"]},
    {"effet": {"echelle": ("fievre", 3)}, "poids": 5, "formes": ["j'ai de la fièvre", "je fais de la fièvre", "je suis fiévreux et j'ai des frissons"]},
    {"effet": {"echelle": ("fievre", 4)}, "poids": 3, "formes": ["j'ai une forte fièvre", "une fièvre très élevée", "je grelotte, fièvre qui monte"]},
    {"effet": {"temperature": None}, "poids": 4, "valeurs": [37.8, 38, 38.5, 39, 39.5, 40, 40.5], "formes": [
        "j'ai de la fièvre à {t}", "température à {t} depuis hier", "je fais {t} de fièvre", "fièvre mesurée à {t}"]},
    {"effet": {"echelle": ("douleur", 5)}, "poids": 2, "formes": ["j'ai une douleur insupportable", "une douleur atroce", "j'ai très très mal, c'est intolérable"]},
    {"effet": {"echelle": ("douleur", 3)}, "poids": 4, "formes": ["j'ai assez mal", "douleur modérée mais gênante", "ça fait mal quand je bouge"]},
    {"effet": {"echelle": ("douleur", 1)}, "poids": 3, "formes": ["une petite douleur", "une gêne légère", "un petit mal qui passe"]},
    {"effet": {"echelle": ("respiration", 3)}, "poids": 3, "formes": ["j'ai du mal à respirer", "je suis essoufflé au moindre effort", "ma respiration est difficile et siffle"]},
    {"effet": {"echelle": ("respiration", 1)}, "poids": 3, "formes": ["un peu essoufflé en montant les escaliers", "je suis légèrement essoufflé"]},
    {"effet": {"echelle": ("etat_general", 5)}, "poids": 2, "formes": [
        "je suis confus et désorienté", "je ne sais plus où je suis", "il est très confus et ne répond plus normalement"]},
    {"effet": {"echelle": ("etat_general", 4)}, "poids": 3, "formes": ["je me sens très mal et très faible", "je suis à bout de forces", "je me sens vraiment très mal"]},
    {"effet": {"echelle": ("etat_general", 2)}, "poids": 4, "formes": ["je ne me sens pas très bien", "je me sens patraque", "je suis un peu barbouillé"]},
    # --- cas bénins qui ressemblent à des cas graves par leurs mots (le modèle doit apprendre à ne pas s'y tromper) ---
    {"effet": {"symptome": "Douleur musculaire ou articulaire", "echelle": ("douleur", 3)}, "poids": 5, "formes": [
        "je me suis foulé le poignet en jouant au football, c'est très enflé", "je me suis fait mal au dos en déménageant, ça tire beaucoup",
        "je me suis tordu le pied dans l'escalier, ça gonfle", "je me suis cogné le genou et j'ai un gros bleu", "je suis tombé du vélo, j'ai mal au coude"]},
    {"effet": {"symptome": "Fatigue"}, "poids": 4, "formes": [
        "je n'arrive plus à dormir à cause du stress", "je n'arrive plus à me concentrer au travail", "je n'arrive plus à rien faire tellement je suis lessivé",
        "je n'ai plus d'appétit et je suis à plat"]},
    {"effet": {"symptome": "Douleur musculaire ou articulaire"}, "poids": 4, "formes": [
        "je n'arrive plus à lever le bras à cause de mon épaule douloureuse", "je n'arrive plus à plier le genou, ça tire",
        "j'ai beaucoup de douleurs dans les jambes en marchant"]},
    {"effet": {"symptome": "Vomissements", "symptome2": "Diarrhée"}, "poids": 3, "formes": [
        "je vomis et j'ai la diarrhée, je ne garde plus rien", "gastro depuis hier, je n'arrive plus à manger"]},
    # --- demandes sans symptôme ------------------------------------------------------------------------------------
    {"effet": {}, "poids": 6, "formes": [
        "je voudrais renouveler mon ordonnance", "je veux un certificat médical pour le sport", "un simple contrôle de routine",
        "je souhaite faire un bilan annuel", "j'ai mes résultats d'analyses à montrer", "rendez-vous de suivi pour mon traitement",
        "je veux me faire vacciner", "une visite de contrôle, tout va bien", "j'ai besoin d'un arrêt de travail pour mon dossier"]},
]

# Ce qui est NIÉ ou concerne un PROCHE ne compte pas : « pas de fièvre », « mon père a eu une douleur à la poitrine ».
NOMS_NIES = [
    "fièvre", "toux", "douleur dans la poitrine", "difficulté à respirer", "vomissements", "maux de tête", "vertiges",
    "perte de connaissance", "saignement", "diarrhée", "douleur au ventre", "éruption", "convulsions", "paralysie",
]
NEGATIONS = ["pas de {x}", "aucun signe de {x}", "sans {x}", "je n'ai pas de {x}", "pas de {x} du tout"]
PROCHES = ["mon père", "ma mère", "mon frère", "ma soeur", "mon mari", "ma voisine", "mon collègue"]
FORMES_PROCHES = ["{p} a eu {x} hier, moi je vais bien", "{p} a {x}, mais moi ça va", "{p} a été soigné pour {x}, ce n'est pas mon cas"]
PASSE = ["il y a deux ans j'ai eu {x}, c'est réglé", "j'ai déjà eu {x} il y a longtemps, aujourd'hui tout va bien"]
NOMS_PROCHES = [
    "une douleur à la poitrine", "de la fièvre", "des convulsions", "un malaise", "une forte toux", "des vomissements", "un saignement",
    "une crise d'épilepsie", "un malaise grave", "une hémorragie", "des douleurs dans le thorax", "une perte de connaissance", "de la fièvre à 40",
]

DEBUTS = ["", "", "", "Bonjour docteur, ", "Bonjour, ", "Bonsoir, ", "Docteur, ", "Salut, "]
LIAISONS = [" et ", ", ", ". ", " et aussi ", " avec ", ", en plus "]
DUREES = ["", "", "", " depuis ce matin", " depuis hier", " depuis trois jours", " depuis une semaine", " depuis une heure", " depuis ce soir"]
FINS = ["", "", ".", " merci", ", merci d'avance", " svp"]
