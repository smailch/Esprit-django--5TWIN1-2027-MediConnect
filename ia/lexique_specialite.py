"""Phrases de patients, par spécialité, pour fabriquer le jeu de données du modèle d'orientation (voir donnees_specialite.py).

Chaque spécialité a des « unités » : une façon de dire un symptôme ou un motif qui oriente vers elle, avec son poids
(fréquence relative). Les phrases sont écrites pour la démonstration, pas des propos de vrais patients. Les noms des
spécialités sont ceux de la liste des médecins du projet (médecins de démonstration : medecins/management/commands/charger_medecins.py).
"""

MEDECINE_GENERALE = "Médecine générale"

SPECIALITES = {
    "Cardiologie": [
        {"poids": 5, "formes": ["j'ai des palpitations", "mon coeur bat trop vite", "mon coeur s'emballe sans raison", "des battements irréguliers dans la poitrine",
                                "j'ai le coeur qui bat très fort au repos", "des palpitations la nuit"]},
        {"poids": 5, "formes": ["j'ai mal à la poitrine quand je fais un effort", "une oppression dans la poitrine quand je monte les escaliers",
                                "ça me serre la poitrine en marchant vite", "une douleur dans la poitrine à l'effort qui passe au repos"]},
        {"poids": 4, "formes": ["ma tension est trop élevée", "je fais de l'hypertension", "ma tension monte à 17", "je voudrais un suivi de ma tension artérielle",
                                "mon tensiomètre affiche des chiffres très hauts"]},
        {"poids": 3, "formes": ["j'ai les chevilles gonflées et je suis essoufflé", "essoufflement à l'effort et jambes qui gonflent",
                                "je fais des malaises à l'effort", "je suis vite essoufflé depuis que j'ai un problème de coeur"]},
        {"poids": 2, "formes": ["je veux faire un bilan cardiaque", "j'ai besoin d'un électrocardiogramme", "un contrôle de mon coeur avant le sport",
                                "mon cholestérol est très haut et mon père a eu un infarctus"]},
    ],
    "Pneumologie": [
        {"poids": 5, "formes": ["je tousse depuis plusieurs semaines", "une toux qui dure depuis un mois", "je tousse tous les matins et je crache",
                                "toux chronique qui ne passe pas", "une toux grasse avec des crachats depuis longtemps"]},
        {"poids": 5, "formes": ["j'ai de l'asthme et je siffle quand je respire", "mon asthme est revenu", "ma respiration siffle la nuit",
                                "j'ai des crises d'asthme plus fréquentes", "je manque de souffle et je siffle"]},
        {"poids": 3, "formes": ["je suis essoufflé en marchant à plat", "j'ai du mal à reprendre mon souffle après un petit effort",
                                "essoufflement depuis plusieurs mois et je fume", "je fume depuis vingt ans et je tousse beaucoup"]},
        {"poids": 3, "formes": ["une bronchite qui traîne", "je fais des bronchites tous les hivers", "j'ai une pneumonie qui ne guérit pas",
                                "je ronfle fort et je fais des pauses respiratoires la nuit", "des apnées du sommeil"]},
        {"poids": 2, "formes": ["je veux une radio des poumons", "un test respiratoire pour mon asthme", "je voudrais arrêter de fumer, je tousse beaucoup"]},
    ],
    "Dermatologie": [
        {"poids": 6, "formes": ["j'ai des boutons sur le visage", "de l'acné qui ne part pas", "des boutons rouges qui grattent sur les bras",
                                "j'ai de l'acné sur le dos et le visage", "ma peau est pleine de boutons"]},
        {"poids": 5, "formes": ["j'ai des plaques rouges qui démangent", "de l'eczéma sur les mains", "ma peau est sèche, rouge et irritée",
                                "des plaques qui pèlent sur les coudes", "du psoriasis qui revient"]},
        {"poids": 3, "formes": ["un grain de beauté a changé de forme", "j'ai un grain de beauté qui grossit et qui saigne", "une tache brune qui s'étend sur la peau"]},
        {"poids": 3, "formes": ["j'ai une mycose entre les orteils", "des verrues sur les doigts", "j'ai des démangeaisons sur tout le corps", "une urticaire qui revient souvent"]},
        {"poids": 2, "formes": ["je perds beaucoup de cheveux", "mes cheveux tombent par plaques", "mes ongles deviennent jaunes et cassants"]},
    ],
    "Gastro-entérologie": [
        {"poids": 6, "formes": ["j'ai des brûlures d'estomac", "du reflux après chaque repas", "des remontées acides toutes les nuits",
                                "j'ai mal à l'estomac après avoir mangé", "un feu dans la poitrine après le repas"]},
        {"poids": 5, "formes": ["j'ai le ventre gonflé et des ballonnements", "des ballonnements à chaque repas", "je suis souvent constipé",
                                "des gaz et le ventre qui gargouille", "une constipation qui dure depuis des semaines"]},
        {"poids": 4, "formes": ["j'ai des diarrhées qui reviennent depuis des mois", "des douleurs au ventre après les repas", "des selles irrégulières depuis longtemps",
                                "j'ai mal au ventre dès que je mange gras"]},
        {"poids": 2, "formes": ["j'ai des nausées après chaque repas", "je digère très mal", "j'ai perdu l'appétit et j'ai mal au ventre depuis des semaines",
                                "du sang dans les selles depuis quelques jours"]},
    ],
    "ORL": [
        {"poids": 6, "formes": ["j'ai mal à l'oreille", "une douleur dans l'oreille depuis hier", "mon oreille est bouchée et me fait mal",
                                "j'ai une otite", "mon oreille coule"]},
        {"poids": 5, "formes": ["j'ai le nez bouché depuis des semaines", "une sinusite qui revient", "j'ai mal au front et aux joues, le nez est bouché",
                                "je n'arrive plus à respirer par le nez", "j'éternue tout le temps et j'ai le nez qui coule"]},
        {"poids": 3, "formes": ["j'ai perdu l'odorat", "je ne sens plus rien depuis des semaines", "j'ai des bourdonnements dans l'oreille", "j'entends moins bien de l'oreille gauche"]},
        {"poids": 3, "formes": ["j'ai des angines à répétition", "ma voix est enrouée depuis un mois", "j'ai mal à la gorge qui revient tout le temps et les amygdales gonflées",
                                "je saigne souvent du nez", "j'ai du mal à avaler depuis plusieurs semaines"]},
    ],
    "Neurologie": [
        {"poids": 6, "formes": ["j'ai des migraines très fréquentes", "des maux de tête presque tous les jours", "mes migraines reviennent chaque semaine avec des nausées",
                                "des maux de tête qui me réveillent la nuit", "une migraine avec des troubles de la vue"]},
        {"poids": 5, "formes": ["j'ai des fourmillements dans les mains", "mon bras est engourdi par moments", "je perds la sensibilité dans les pieds",
                                "des picotements dans la jambe qui reviennent", "mes doigts s'engourdissent la nuit"]},
        {"poids": 4, "formes": ["j'ai des tremblements des mains", "mes mains tremblent de plus en plus", "j'ai des pertes de mémoire de plus en plus fréquentes",
                                "j'oublie tout depuis quelques mois", "j'ai du mal à me concentrer et à me souvenir"]},
        {"poids": 3, "formes": ["j'ai des vertiges très fréquents", "des vertiges qui reviennent avec des bourdonnements", "j'ai des crises où je perds l'équilibre",
                                "j'ai déjà fait une crise d'épilepsie il y a longtemps et je veux un suivi"]},
    ],
    "Rhumatologie": [
        {"poids": 6, "formes": ["j'ai mal au dos depuis des semaines", "une douleur dans le bas du dos qui descend dans la jambe", "une sciatique qui ne passe pas",
                                "j'ai un lumbago", "mon dos est bloqué le matin"]},
        {"poids": 6, "formes": ["j'ai mal au genou quand je marche", "mes articulations sont raides et douloureuses", "mes doigts sont gonflés et douloureux le matin",
                                "de l'arthrose dans les mains", "j'ai mal aux hanches en me levant"]},
        {"poids": 4, "formes": ["j'ai mal à l'épaule et je n'arrive plus à lever le bras", "une tendinite au coude", "une douleur au poignet qui revient",
                                "j'ai mal à la nuque depuis des semaines"]},
        {"poids": 2, "formes": ["je me suis fait une entorse à la cheville", "je me suis foulé le poignet", "je me suis tordu le genou en jouant au football"]},
    ],
    MEDECINE_GENERALE: [
        {"poids": 6, "formes": ["j'ai un rhume", "je suis enrhumé depuis deux jours", "j'ai de la fièvre et des courbatures", "je crois que j'ai la grippe",
                                "j'ai de la fièvre et mal à la gorge", "un début de rhume avec le nez qui coule"]},
        {"poids": 5, "formes": ["je suis très fatigué en ce moment", "je suis épuisé depuis quelques jours", "je me sens patraque", "je n'ai pas d'énergie et je dors mal",
                                "j'ai des maux de tête depuis ce matin", "j'ai mal à la tête et un peu de fièvre"]},
        {"poids": 5, "formes": ["je voudrais renouveler mon ordonnance", "je veux un certificat médical pour le sport", "un simple contrôle de routine",
                                "je souhaite faire un bilan annuel", "j'ai besoin d'un arrêt de travail", "je veux me faire vacciner", "une visite de contrôle, tout va bien"]},
        {"poids": 4, "formes": ["j'ai la gastro, je vomis et j'ai la diarrhée depuis hier", "j'ai de la diarrhée depuis ce matin", "je vomis depuis hier soir",
                                "j'ai mal au ventre et un peu de nausées depuis ce matin"]},
        {"poids": 4, "formes": ["je tousse depuis deux jours avec de la fièvre", "j'ai une toux et de la fièvre", "une angine avec de la fièvre", "j'ai mal à la gorge depuis hier"]},
        {"poids": 3, "formes": ["j'ai mal", "j'ai mal un peu partout", "je suis malade", "je ne me sens pas bien", "ça ne va pas du tout", "j'ai une douleur",
                                "je ne sais pas ce que j'ai", "je voudrais voir un médecin", "j'ai besoin d'une consultation"]},
        {"poids": 3, "formes": ["j'ai mes résultats d'analyses à montrer", "un rendez-vous de suivi pour mon traitement", "je veux un avis, je ne sais pas à qui m'adresser",
                                "j'ai des symptômes que je n'arrive pas à expliquer", "je ne me sens pas bien mais je ne sais pas pourquoi"]},
    ],
}

# Pédiatrie : un enfant est concerné. Le symptôme seul ne suffit pas : c'est la mention de l'enfant qui oriente.
PEDIATRIE = "Pédiatrie"
ENFANTS = [
    "mon fils", "ma fille", "mon bébé", "mon enfant", "mon petit garçon", "ma petite fille", "mon fils de 3 ans", "ma fille de 6 ans", "mon bébé de 8 mois",
    "mon enfant de 2 ans", "mon nourrisson", "ma fille de 10 ans", "mon fils de 12 ans", "notre bébé", "ma petite de 4 ans",
]
SYMPTOMES_ENFANT = [
    "a de la fièvre depuis hier", "tousse beaucoup la nuit", "a le nez qui coule et ne mange plus", "vomit depuis ce matin", "a la diarrhée depuis deux jours",
    "a des boutons sur le corps", "se plaint de mal au ventre", "pleure beaucoup et dort mal", "a mal à l'oreille", "a mal à la gorge et ne veut plus manger",
    "ne grandit pas assez vite", "est très fatigué depuis quelques jours", "a une toux qui siffle", "a mal à la tête depuis hier", "refuse de boire",
    "a besoin de ses vaccins", "doit faire son bilan de croissance", "a la varicelle je pense", "a les yeux rouges et qui collent", "est très grognon et a un peu de température",
]

# Mots qui n'orientent vers aucune spécialité : le patient parle d'un proche ou nie un symptôme -> médecine générale.
NEGATIONS = ["pas de {x}", "aucun signe de {x}", "sans {x}", "je n'ai pas de {x}"]
NOMS_NIES = ["fièvre", "toux", "douleur dans la poitrine", "vomissements", "boutons", "mal de ventre", "mal de dos", "migraine"]
FORMES_PROCHES = ["{p} a eu {x} hier, moi je vais bien", "{p} a {x}, mais moi ça va", "{p} a été soigné pour {x}, ce n'est pas mon cas"]
PROCHES = ["mon père", "ma mère", "mon frère", "ma soeur", "mon mari", "ma voisine", "mon collègue"]
NOMS_PROCHES = ["une douleur à la poitrine", "de l'asthme", "de l'eczéma", "des migraines", "un mal de dos", "une otite", "des brûlures d'estomac"]

# Ce que soigne chaque spécialité, en mots simples (affiché au patient).
DOMAINES = {
    "Médecine générale": "le premier avis, les symptômes courants (rhume, fièvre, fatigue) et le suivi",
    "Cardiologie": "le coeur et la tension artérielle",
    "Pneumologie": "les poumons et la respiration",
    "Dermatologie": "la peau, les cheveux et les ongles",
    "Gastro-entérologie": "l'estomac, l'intestin et la digestion",
    "ORL": "les oreilles, le nez et la gorge",
    "Neurologie": "les nerfs, la mémoire et les maux de tête fréquents",
    "Rhumatologie": "les articulations, le dos et les muscles",
    "Pédiatrie": "la santé des enfants",
}
