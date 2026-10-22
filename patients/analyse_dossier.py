"""Analyse automatique du dossier médical : un assistant à règles, sans envoi de données.

Logique pure (sans base de données). À partir de ce que le patient a saisi (antécédents, traitements,
allergies, mesures), l'assistant :

* repère les antécédents et les traitements écrits en texte libre (avec gestion de la négation) ;
* détecte les conflits (traitement de la même famille qu'une allergie, anticoagulant avec un
  anti-inflammatoire) et les incohérences (traitement sans l'antécédent correspondant) ;
* lit les mesures récentes (tension, glycémie, saturation, température, pouls, poids) ;
* calcule la complétude du dossier, un résumé et un niveau de vigilance.

C'est une aide à la vigilance, pas un diagnostic. Les seuils et les listes sont des valeurs de démonstration
à faire valider par un professionnel de santé avant tout usage réel. Chaque remarque dit pourquoi elle est faite.
"""
import datetime
import re
import unicodedata
from dataclasses import dataclass, field

IMPORTANT, ATTENTION, INFO = "important", "attention", "info"
CALME, A_SURVEILLER = "calme", "a_surveiller"
ORDRE_GRAVITE = {IMPORTANT: 0, ATTENTION: 1, INFO: 2}
FENETRE_RECENTE_JOURS = 30  # les alertes de mesures ne portent que sur le dernier mois
FENETRE_SUIVI_JOURS = 90  # « pas de mesure récente » à partir de trois mois
NEGATIONS = {"pas", "aucun", "aucune", "sans", "non", "jamais", "ni", "nul", "nulle"}
# « mon père est diabétique » : un antécédent familial n'est pas celui du patient
FAMILLE_PROCHE = {"pere", "mere", "frere", "soeur", "famille", "parents", "oncle", "tante", "fils", "fille", "mari", "epoux", "epouse"}

# --- vocabulaire ----------------------------------------------------------------------------------
# Les termes sont écrits sans accents ni majuscules (le texte du patient est normalisé avant comparaison).

FAMILLES = {
    "penicillines": ("pénicillines", ["penicilline", "penicillines", "amoxicilline", "ampicilline", "augmentin", "clamoxyl", "oracilline", "bristopen", "amoxil"]),
    "cephalosporines": ("céphalosporines", ["cephalosporine", "cephalosporines", "cefixime", "cefuroxime", "ceftriaxone", "cefalexine", "cefadroxil", "cefpodoxime"]),
    "ains": ("anti-inflammatoires (aspirine, ibuprofène…)", ["aspirine", "kardegic", "aspegic", "ibuprofene", "advil", "nurofen", "diclofenac", "voltarene", "ketoprofene", "profenid", "naproxene", "anti inflammatoire", "anti inflammatoires", "ains"]),
    "sulfamides": ("sulfamides", ["sulfamide", "sulfamides", "bactrim", "cotrimoxazole", "sulfamethoxazole"]),
    "macrolides": ("macrolides", ["azithromycine", "clarithromycine", "erythromycine", "zithromax"]),
    "quinolones": ("quinolones", ["ciprofloxacine", "levofloxacine", "ofloxacine", "norfloxacine"]),
    "paracetamol": ("paracétamol", ["paracetamol", "doliprane", "efferalgan", "dafalgan"]),
}

CONDITIONS = {
    "diabète": ["diabete", "diabetique", "dt1", "dt2"],
    "hypertension": ["hypertension", "hta", "tension elevee", "hypertendu", "hypertendue"],
    "asthme": ["asthme", "asthmatique"],
    "maladie cardiaque": ["infarctus", "angine de poitrine", "insuffisance cardiaque", "arythmie", "fibrillation", "cardiopathie", "pacemaker", "stent"],
    "insuffisance rénale": ["insuffisance renale", "dialyse"],
    "épilepsie": ["epilepsie", "epileptique"],
    "problème de thyroïde": ["hypothyroidie", "hyperthyroidie", "thyroide"],
    "cholestérol élevé": ["cholesterol", "hypercholesterolemie", "dyslipidemie"],
    "BPCO": ["bpco", "bronchite chronique", "emphyseme"],
    "AVC": ["avc", "accident vasculaire cerebral"],
    "cancer": ["cancer", "tumeur", "chimiotherapie"],
    "grossesse": ["enceinte", "grossesse"],
    "dépression ou anxiété": ["depression", "depressif", "depressive", "anxiete", "anxieux", "anxieuse"],
    "anémie": ["anemie", "anemique"],
    "migraine": ["migraine", "migraines"],
    "obésité": ["obesite", "obese"],
    "tabagisme": ["fumeur", "fumeuse", "tabagisme", "tabac"],
}

# nom, termes, classe, antécédents attendus (l'un d'eux suffit ; vide = aucun)
MEDICAMENTS = {
    "metformine": (["metformine", "glucophage", "stagid"], "antidiabétique", ["diabète"]),
    "insuline": (["insuline", "lantus", "novorapid", "humalog"], "insuline", ["diabète"]),
    "gliclazide": (["gliclazide", "diamicron"], "antidiabétique", ["diabète"]),
    "salbutamol": (["ventoline", "salbutamol", "bricanyl", "terbutaline"], "bronchodilatateur", ["asthme", "BPCO"]),
    "corticoïde inhalé": (["symbicort", "seretide", "flixotide", "pulmicort", "budesonide"], "traitement de fond respiratoire", ["asthme", "BPCO"]),
    "amlodipine": (["amlodipine", "amlor", "loxen"], "antihypertenseur", ["hypertension", "maladie cardiaque"]),
    "IEC": (["ramipril", "triatec", "enalapril", "perindopril", "coversyl", "lisinopril"], "antihypertenseur", ["hypertension", "maladie cardiaque"]),
    "sartan": (["losartan", "cozaar", "valsartan", "irbesartan", "candesartan"], "antihypertenseur", ["hypertension", "maladie cardiaque"]),
    "bêtabloquant": (["bisoprolol", "cardensiel", "atenolol", "metoprolol", "propranolol"], "bêtabloquant", ["hypertension", "maladie cardiaque"]),
    "statine": (["atorvastatine", "tahor", "simvastatine", "zocor", "rosuvastatine", "crestor"], "anti-cholestérol", ["cholestérol élevé", "maladie cardiaque", "diabète"]),
    "lévothyroxine": (["levothyrox", "levothyroxine", "l thyroxine"], "hormone thyroïdienne", ["problème de thyroïde"]),
    "anticoagulant": (["warfarine", "coumadine", "previscan", "fluindione", "acenocoumarol", "sintrom", "apixaban", "eliquis", "rivaroxaban", "xarelto", "dabigatran", "pradaxa"], "anticoagulant", []),
    "antidépresseur": (["sertraline", "zoloft", "fluoxetine", "prozac", "escitalopram", "seroplex", "paroxetine", "deroxat"], "antidépresseur", ["dépression ou anxiété"]),
    "antiépileptique": (["levetiracetam", "keppra", "carbamazepine", "tegretol", "valproate", "depakine", "lamotrigine", "lamictal"], "antiépileptique", ["épilepsie"]),
}

# --- outils de texte -----------------------------------------------------------------------------


def normaliser(texte):
    """Minuscules, sans accents ni ponctuation : « Pénicilline, 2x/jour » -> « penicilline 2x jour »."""
    sans_accents = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


def _segments(texte):
    """Découpe le texte en propositions (virgule, point, point-virgule, retour à la ligne) : la négation
    d'une proposition (« pas de diabète ») ne touche pas la suivante."""
    return [normaliser(s) for s in re.split(r"[.;,\n]+", texte or "") if normaliser(s)]


def _trouver(texte, table):
    """Clés de `table` ({clé: [termes]}) présentes dans le texte. Un terme est ignoré s'il est nié
    (« pas de diabète ») ou s'il concerne un proche (« mon père est diabétique »)."""
    trouvees = []
    for segment in _segments(texte):
        for cle, termes in table.items():
            for terme in termes:
                for m in re.finditer(rf"(?<![a-z0-9]){re.escape(terme)}(?![a-z0-9])", segment):
                    avant = set(segment[: m.start()].split()[-3:])
                    if not (NEGATIONS | FAMILLE_PROCHE) & avant and cle not in trouvees:
                        trouvees.append(cle)
    return trouvees


def conditions_reperees(antecedents):
    return _trouver(antecedents, CONDITIONS)


def medicaments_reperes(traitements):
    return _trouver(traitements, {cle: v[0] for cle, v in MEDICAMENTS.items()})


def familles_de(texte):
    """Familles de médicaments (pénicillines, anti-inflammatoires…) citées dans un texte."""
    return _trouver(texte, {cle: v[1] for cle, v in FAMILLES.items()})


# --- résultat ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Point:
    gravite: str  # important | attention | info
    titre: str
    detail: str
    pourquoi: str  # explication de la règle : l'analyse ne doit jamais être une boîte noire
    action: str = ""  # rdv | completer | allergies | mesures | mesure_nouvelle | (vide)


@dataclass
class Analyse:
    resume: str
    vigilance: str
    message: str
    points: list = field(default_factory=list)
    profil: list = field(default_factory=list)
    completude: int = 0
    manquants: list = field(default_factory=list)
    lu: dict = field(default_factory=dict)

    @property
    def importants(self):
        return [p for p in self.points if p.gravite == IMPORTANT]

    @property
    def attentions(self):
        return [p for p in self.points if p.gravite == ATTENTION]

    @property
    def infos(self):
        return [p for p in self.points if p.gravite == INFO]


MESSAGES_VIGILANCE = {
    CALME: "Rien d'inquiétant n'a été repéré dans les informations que vous avez saisies.",
    A_SURVEILLER: "Quelques points sont à évoquer avec votre médecin lors de votre prochain rendez-vous.",
    IMPORTANT: "Des éléments de votre dossier méritent l'avis d'un médecin ou d'un pharmacien rapidement.",
}


# --- règles : traitements, allergies, antécédents ------------------------------------------------------


def _libelle_famille(cle):
    return FAMILLES[cle][0]


def _points_allergies_traitements(allergies, traitements):
    points = []
    actives = [a for a in allergies if a.get("active", True)]
    familles_traitement = {}  # famille -> premier médicament cité qui en fait partie
    for segment in _segments(traitements):
        for cle, (_, termes) in FAMILLES.items():
            for terme in termes:
                if re.search(rf"(?<![a-z0-9]){re.escape(terme)}(?![a-z0-9])", segment) and cle not in familles_traitement:
                    familles_traitement[cle] = terme
    for a in actives:
        substance = a.get("substance", "")
        familles_allergie = familles_de(substance)
        for cle in familles_allergie:
            if cle in familles_traitement:
                points.append(Point(
                    IMPORTANT, "Traitement et allergie de la même famille",
                    f"Votre traitement mentionne « {familles_traitement[cle]} », de la famille des {_libelle_famille(cle)}, "
                    f"et vous avez déclaré une allergie à « {substance} ». Parlez-en à votre médecin ou à votre pharmacien avant de le prendre.",
                    f"Le médicament cité ({familles_traitement[cle]}) et l'allergie ({substance}) appartiennent à la même famille : {_libelle_famille(cle)}.",
                    "rdv",
                ))
        if "penicillines" in familles_allergie and "cephalosporines" in familles_traitement:
            points.append(Point(
                ATTENTION, "Réaction croisée possible",
                f"Vous êtes allergique à « {substance} » et votre traitement mentionne « {familles_traitement['cephalosporines']} » "
                "(céphalosporine). Une réaction croisée est possible : demandez l'avis de votre médecin.",
                "Les pénicillines et les céphalosporines sont des antibiotiques proches : une allergie à l'une peut parfois concerner l'autre.",
                "rdv",
            ))
    return points


def _points_interactions(medicaments, traitements):
    points = []
    if "anticoagulant" in medicaments and "ains" in familles_de(traitements):
        points.append(Point(
            IMPORTANT, "Anticoagulant et anti-inflammatoire",
            "Votre traitement mentionne un anticoagulant et un anti-inflammatoire (aspirine, ibuprofène…). "
            "Cette association augmente le risque de saignement : demandez l'avis de votre médecin ou de votre pharmacien.",
            "Les anti-inflammatoires associés à un anticoagulant augmentent le risque de saignement.",
            "rdv",
        ))
    return points


def _points_coherence(medicaments, conditions):
    points = []
    for cle in medicaments:
        _, classe, attendus = MEDICAMENTS[cle]
        if attendus and not set(attendus) & set(conditions):
            points.append(Point(
                INFO, f"Un antécédent semble manquer ({attendus[0]})",
                f"Vous indiquez un traitement de type « {classe} », mais « {attendus[0]} » n'apparaît pas dans vos antécédents. "
                "Si cela vous concerne, précisez-le : le médecin aura un dossier plus complet.",
                f"Un traitement « {classe} » est habituellement prescrit pour : {', '.join(attendus)}.",
                "completer",
            ))
    return points


# --- règles : mesures ----------------------------------------------------------------------------------


def _recentes(mesures, type_, maintenant, jours):
    debut = maintenant - datetime.timedelta(days=jours)
    return sorted((m for m in mesures if m["type"] == type_ and m["mesure_le"] >= debut), key=lambda m: m["mesure_le"])


def _tension(m):
    """(gravité, texte) d'une tension systolique/diastolique, ou None si normale."""
    s, d = m["valeur"], m.get("valeur2")
    if s >= 180 or (d is not None and d >= 110):
        return IMPORTANT, "très élevée"
    if s < 80:
        return IMPORTANT, "très basse"
    if s >= 140 or (d is not None and d >= 90):
        return ATTENTION, "élevée"
    if s < 90 or (d is not None and d < 60):
        return ATTENTION, "basse"
    return None


def _points_mesures(mesures, maintenant, conditions):
    points = []

    def ajouter(gravite, titre, detail, pourquoi, action="rdv"):
        points.append(Point(gravite, titre, detail, pourquoi, action))

    tensions = _recentes(mesures, "tension", maintenant, FENETRE_RECENTE_JOURS)
    if tensions:
        derniere = tensions[-1]
        etat = _tension(derniere)
        anormales = [m for m in tensions if _tension(m)]
        valeur = f"{derniere['valeur']:g}/{derniere['valeur2']:g}" if derniere.get("valeur2") is not None else f"{derniere['valeur']:g}"
        if etat and etat[0] == IMPORTANT:
            ajouter(IMPORTANT, f"Tension {etat[1]}", f"Votre dernière tension est de {valeur} mmHg ({etat[1]}). Consultez rapidement un médecin ; en cas de malaise, de maux de tête violents ou de douleur dans la poitrine, appelez le 190, le 15 ou le 112.",
                    f"La dernière mesure de tension ({valeur}) dépasse le seuil d'alerte (180/110 ou moins de 80).")
        elif len(anormales) >= 2:
            ajouter(ATTENTION, "Tension anormale à plusieurs reprises", f"{len(anormales)} de vos mesures de tension du dernier mois sont hors de la normale (dernière : {valeur} mmHg). À évoquer avec votre médecin.",
                    "Au moins deux mesures de tension sur les 30 derniers jours sont au-dessus de 140/90 ou en dessous de 90/60.")
        elif etat:
            ajouter(ATTENTION, f"Tension {etat[1]}", f"Votre dernière tension est de {valeur} mmHg ({etat[1]}). Refaites une mesure au repos et notez-la.",
                    "Une seule mesure hors de la normale : l'analyse conseille de la confirmer.", "mesure_nouvelle")

    glycemies = _recentes(mesures, "glycemie", maintenant, FENETRE_RECENTE_JOURS)
    if glycemies:
        g = glycemies[-1]["valeur"]
        if g >= 2.0:
            ajouter(IMPORTANT, "Glycémie très élevée", f"Votre dernière glycémie est de {g:g} g/L. Consultez un médecin rapidement.", "Une glycémie de 2 g/L ou plus est un seuil d'alerte, à jeun ou non.")
        elif g < 0.54:
            ajouter(IMPORTANT, "Glycémie très basse", f"Votre dernière glycémie est de {g:g} g/L. Consultez un médecin rapidement.", "Une glycémie inférieure à 0,54 g/L est un seuil d'alerte.")
        elif g >= 1.26:
            ajouter(ATTENTION, "Glycémie élevée", f"Votre dernière glycémie est de {g:g} g/L. Si elle a été mesurée à jeun, parlez-en à votre médecin.", "Une glycémie à jeun de 1,26 g/L ou plus est au-dessus de la norme.")
        elif g < 0.7:
            ajouter(ATTENTION, "Glycémie basse", f"Votre dernière glycémie est de {g:g} g/L.", "Une glycémie inférieure à 0,7 g/L est en dessous de la norme.")

    saturations = _recentes(mesures, "saturation", maintenant, FENETRE_RECENTE_JOURS)
    if saturations:
        s = saturations[-1]["valeur"]
        if s < 90:
            ajouter(IMPORTANT, "Saturation en oxygène très basse", f"Votre dernière saturation est de {s:g} %. Appelez le 15 ou le 112 si vous avez du mal à respirer ; sinon consultez rapidement.", "Une saturation inférieure à 90 % est un seuil d'alerte.")
        elif s < 94:
            ajouter(ATTENTION, "Saturation en oxygène basse", f"Votre dernière saturation est de {s:g} %. Refaites la mesure au repos et parlez-en à votre médecin.", "Une saturation inférieure à 94 % est en dessous de la norme.")

    temperatures = _recentes(mesures, "temperature", maintenant, 7)  # une fièvre ne compte que quelques jours
    if temperatures:
        t = temperatures[-1]["valeur"]
        if t >= 40:
            ajouter(IMPORTANT, "Fièvre très élevée", f"Votre dernière température est de {t:g} °C. Consultez rapidement.", "Une température de 40 °C ou plus est un seuil d'alerte.")
        elif t >= 38:
            ajouter(ATTENTION, "Fièvre", f"Votre dernière température est de {t:g} °C. Surveillez-la et consultez si elle dure.", "Une température de 38 °C ou plus est de la fièvre.")
        elif t < 35.5:
            ajouter(ATTENTION, "Température basse", f"Votre dernière température est de {t:g} °C.", "Une température inférieure à 35,5 °C est en dessous de la norme.")

    pouls = _recentes(mesures, "frequence", maintenant, FENETRE_RECENTE_JOURS)
    if pouls:
        f = pouls[-1]["valeur"]
        if f > 130 or f < 40:
            ajouter(IMPORTANT, "Pouls très anormal", f"Votre dernier pouls est de {f:g} battements par minute. Consultez rapidement.", "Un pouls au repos au-dessus de 130 ou en dessous de 40 est un seuil d'alerte.")
        elif f > 100 or f < 50:
            ajouter(ATTENTION, "Pouls inhabituel", f"Votre dernier pouls est de {f:g} battements par minute.", "Un pouls au repos au-dessus de 100 ou en dessous de 50 est inhabituel.")

    poids = _recentes(mesures, "poids", maintenant, FENETRE_RECENTE_JOURS)
    if len(poids) >= 2 and poids[0]["valeur"] > 0:
        variation = (poids[-1]["valeur"] - poids[0]["valeur"]) / poids[0]["valeur"] * 100
        if abs(variation) >= 5:
            sens = "pris" if variation > 0 else "perdu"
            ajouter(ATTENTION, "Variation de poids importante", f"Vous avez {sens} {abs(variation):.0f} % de votre poids en moins d'un mois ({poids[0]['valeur']:g} kg puis {poids[-1]['valeur']:g} kg). À évoquer avec votre médecin si ce n'est pas voulu.",
                    "Une variation de 5 % du poids ou plus en 30 jours mérite un avis.")

    suivis = (("hypertension", "tension", "tension"), ("diabète", "glycemie", "glycémie"))
    for condition, type_, nom in suivis:
        if condition in conditions and not _recentes(mesures, type_, maintenant, FENETRE_SUIVI_JOURS):
            ajouter(INFO, f"Aucune mesure de {nom} récente", f"Votre dossier mentionne « {condition} » mais aucune mesure de {nom} n'a été enregistrée ces trois derniers mois.",
                    f"Le suivi régulier de la {nom} est utile quand on a : {condition}.", "mesure_nouvelle")
    return points


# --- règles : complétude et allergies ------------------------------------------------------------------


def _points_completude(manquants, allergies):
    points = []
    if manquants:
        points.append(Point(INFO, "Des informations utiles manquent", "À compléter : " + ", ".join(m.lower() for m in manquants) + ".",
                            "Ces informations sont lues par le médecin avant la consultation.", "completer"))
    if not allergies:
        points.append(Point(INFO, "Aucune allergie enregistrée", "Si vous n'avez aucune allergie connue, vous n'avez rien à faire. Sinon, ajoutez-les : c'est une information de sécurité.",
                            "Aucune allergie n'est enregistrée dans votre dossier.", "allergies"))
    return points


# --- assemblage -----------------------------------------------------------------------------------------


def _resume(age, sexe, groupe_sanguin, allergies, conditions, medicaments, mesures, maintenant):
    morceaux = [f"{'Femme' if sexe == 'F' else 'Homme'} de {age} ans"]
    if groupe_sanguin:
        morceaux.append(f"groupe sanguin {groupe_sanguin}")
    actives = [a for a in allergies if a.get("active", True)]
    severes = [a["substance"] for a in actives if a.get("gravite") == "severe"]
    if severes:
        morceaux.append("allergie sévère à " + ", ".join(severes))
    elif actives:
        morceaux.append(f"{len(actives)} allergie{'s' if len(actives) > 1 else ''} enregistrée{'s' if len(actives) > 1 else ''}")
    if conditions:
        morceaux.append("antécédents repérés : " + ", ".join(conditions))
    if medicaments:
        morceaux.append(f"{len(medicaments)} type{'s' if len(medicaments) > 1 else ''} de traitement reconnu{'s' if len(medicaments) > 1 else ''}")
    derniere = {}
    for m in sorted(mesures, key=lambda m: m["mesure_le"]):
        derniere[m["type"]] = m
    recents = []
    for type_, nom, unite in (("tension", "tension", "mmHg"), ("glycemie", "glycémie", "g/L"), ("poids", "poids", "kg")):
        m = derniere.get(type_)
        if m and m["mesure_le"] >= maintenant - datetime.timedelta(days=FENETRE_SUIVI_JOURS):
            valeur = f"{m['valeur']:g}/{m['valeur2']:g}" if m.get("valeur2") is not None else f"{m['valeur']:g}"
            recents.append(f"{nom} {valeur} {unite}")
    if recents:
        morceaux.append("dernières mesures : " + ", ".join(recents))
    return " · ".join(morceaux) + "."


def analyser(*, age, sexe, groupe_sanguin, antecedents, traitements, allergies, mesures, manquants, total_controles, maintenant):
    """Analyse complète. `allergies` : [{substance, gravite, active}] ; `mesures` : [{type, valeur, valeur2, mesure_le}].
    `manquants` : informations utiles non renseignées (voir patients.dossier) sur `total_controles` contrôles.
    """
    conditions = conditions_reperees(antecedents)
    medicaments = medicaments_reperes(traitements)
    points = []
    points += _points_allergies_traitements(allergies, traitements)
    points += _points_interactions(medicaments, traitements)
    points += _points_mesures(mesures, maintenant, conditions)
    points += _points_coherence(medicaments, conditions)
    points += _points_completude(manquants, allergies)
    points.sort(key=lambda p: ORDRE_GRAVITE[p.gravite])  # tri stable : l'ordre des règles est conservé à gravité égale

    if any(p.gravite == IMPORTANT for p in points):
        vigilance = IMPORTANT
    elif any(p.gravite == ATTENTION for p in points):
        vigilance = A_SURVEILLER
    else:
        vigilance = CALME
    completude = round(100 * (total_controles - len(manquants)) / total_controles) if total_controles else 100
    return Analyse(
        resume=_resume(age, sexe, groupe_sanguin, allergies, conditions, medicaments, mesures, maintenant),
        vigilance=vigilance,
        message=MESSAGES_VIGILANCE[vigilance],
        points=points,
        profil=conditions,
        completude=completude,
        manquants=list(manquants),
        lu={
            "antecedents": len(conditions),
            "traitements": len(medicaments),
            "allergies": sum(1 for a in allergies if a.get("active", True)),
            "mesures": sum(1 for m in mesures if m["mesure_le"] >= maintenant - datetime.timedelta(days=FENETRE_RECENTE_JOURS)),
        },
    )
