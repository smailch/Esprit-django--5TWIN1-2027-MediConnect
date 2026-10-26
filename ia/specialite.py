"""Le modèle qui oriente un patient vers une SPÉCIALITÉ à partir de ce qu'il écrit (« Quel médecin consulter ? »).

Même famille que le modèle de triage : TF-IDF (mots et groupes de lettres, tolérant aux fautes) puis régression
logistique, quelques Ko, aucun GPU. Il est entraîné sur un jeu SYNTHÉTIQUE généré à partir de lexique_specialite.py :
c'est un prototype d'orientation, pas un diagnostic. Il ne propose une spécialité que s'il est assez sûr de lui ;
sinon il oriente vers la médecine générale (voir conseiller()).
"""
import json
import logging
import random
import threading
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import f1_score

from . import donnees, lexique as lx, lexique_specialite as ls, modele

journal = logging.getLogger("mediconnect.ia")

DOSSIER_ARTEFACTS = modele.DOSSIER_ARTEFACTS
NOM_MODELE, NOM_EVALUATION = "specialite_texte.joblib", "evaluation_specialite.json"
CLASSES = [ls.MEDECINE_GENERALE, ls.PEDIATRIE, *[s for s in ls.SPECIALITES if s != ls.MEDECINE_GENERALE]]
SEUIL_PAR_DEFAUT = 0.70  # confiance minimale pour proposer une spécialité ; en dessous, on ne devine pas
TAILLE_ENTRAINEMENT, TAILLE_TEST = 5400, 1350

_verrou = threading.Lock()
_etat = {"modele": None, "tente": False}


# --- jeu de données -----------------------------------------------------------------------------------------------

def _morceau_de(specialite, rng):
    unites = ls.SPECIALITES[specialite]
    u = rng.choices(unites, weights=[x["poids"] for x in unites])[0]
    return rng.choice(u["formes"])


def _phrase_pediatrie(rng):
    return f"{rng.choice(ls.ENFANTS)} {rng.choice(ls.SYMPTOMES_ENFANT)}"


def _phrase_de(specialite, rng):
    if specialite == ls.PEDIATRIE:
        morceaux = [_phrase_pediatrie(rng)]
    else:
        morceaux = [_morceau_de(specialite, rng)]
        if rng.random() < 0.35:  # un second signe de la même spécialité
            autre = _morceau_de(specialite, rng)
            if autre not in morceaux:
                morceaux.append(autre)
    if rng.random() < 0.18:  # un symptôme nié : il n'oriente vers rien
        morceaux.append(rng.choice(ls.NEGATIONS).format(x=rng.choice(ls.NOMS_NIES)))
    rng.shuffle(morceaux)
    texte = morceaux[0] + rng.choice(lx.DUREES)
    for m in morceaux[1:]:
        texte += rng.choice(lx.LIAISONS) + m
    return donnees._bruiter(rng.choice(lx.DEBUTS) + texte + rng.choice(lx.FINS), rng)


def _phrase_sans_signe(rng):
    """Un proche malade ou des symptômes niés : rien n'oriente, donc médecine générale."""
    if rng.random() < 0.5:
        texte = rng.choice(ls.FORMES_PROCHES).format(p=rng.choice(ls.PROCHES), x=rng.choice(ls.NOMS_PROCHES))
    else:
        texte = ", ".join(rng.choice(ls.NEGATIONS).format(x=x) for x in rng.sample(ls.NOMS_NIES, 2)) + ", juste un contrôle"
    return donnees._bruiter(rng.choice(lx.DEBUTS) + texte + rng.choice(lx.FINS), rng)


def generer(n, graine=1):
    """n phrases [(texte, spécialité)], réparties à parts égales entre les spécialités, toujours les mêmes pour une graine."""
    rng = random.Random(graine)
    sortie = []
    par_classe = n // len(CLASSES)
    for specialite in CLASSES:
        for _ in range(par_classe):
            if specialite == ls.MEDECINE_GENERALE and rng.random() < 0.15:
                sortie.append((_phrase_sans_signe(rng), specialite))
            else:
                sortie.append((_phrase_de(specialite, rng), specialite))
    rng.shuffle(sortie)
    return sortie


# Phrases écrites à la main, hors du lexique : un contrôle de ce que le modèle a vraiment appris.
PHRASES_A_LA_MAIN = [
    ("Depuis une semaine mon coeur cogne très fort le soir et j'ai peur", "Cardiologie"),
    ("J'ai mal dans la poitrine dès que je cours un peu", "Cardiologie"),
    ("Mon médecin m'a dit que j'ai de l'hypertension et je dois voir quelqu'un", "Cardiologie"),
    ("Je tousse sans arrêt depuis un mois et je suis fumeur", "Pneumologie"),
    ("Je siffle quand je respire, surtout la nuit, j'ai de l'asthme", "Pneumologie"),
    ("Ça fait des semaines que je manque de souffle dans les escaliers et que je tousse", "Pneumologie"),
    ("J'ai plein de boutons rouges sur le visage depuis des mois", "Dermatologie"),
    ("Une plaque rouge qui gratte beaucoup sur mon bras, on dirait de l'eczéma", "Dermatologie"),
    ("J'ai un grain de beauté qui a grossi récemment", "Dermatologie"),
    ("Mon estomac me brûle après chaque repas", "Gastro-entérologie"),
    ("Constipation et ballonnements depuis plusieurs semaines", "Gastro-entérologie"),
    ("Je digère mal et j'ai souvent mal au ventre après manger", "Gastro-entérologie"),
    ("Mon oreille me fait très mal depuis ce matin", "ORL"),
    ("J'ai le nez complètement bouché et mal aux joues depuis des jours", "ORL"),
    ("Je n'entends plus bien de l'oreille droite", "ORL"),
    ("J'ai des migraines presque chaque semaine avec des nausées", "Neurologie"),
    ("Mes mains tremblent de plus en plus et j'oublie des choses", "Neurologie"),
    ("J'ai des fourmillements dans le bras gauche qui reviennent", "Neurologie"),
    ("J'ai très mal au bas du dos et ça descend dans la jambe", "Rhumatologie"),
    ("Mes genoux me font mal à chaque pas, je crois que c'est de l'arthrose", "Rhumatologie"),
    ("Douleur à l'épaule depuis un mois, je ne peux plus porter mon sac", "Rhumatologie"),
    ("Mon fils de 5 ans a de la fièvre et se plaint de la gorge", "Pédiatrie"),
    ("Ma petite fille tousse toute la nuit et ne veut plus manger", "Pédiatrie"),
    ("Mon bébé a des boutons partout et pleure beaucoup", "Pédiatrie"),
    ("J'ai un gros rhume et un peu de fièvre depuis deux jours", "Médecine générale"),
    ("Je voudrais un certificat médical et un contrôle général", "Médecine générale"),
    ("Je suis fatigué et je dors mal, je ne sais pas pourquoi", "Médecine générale"),
    ("Je dois renouveler mon ordonnance", "Médecine générale"),
    ("Mon père a eu une douleur à la poitrine hier, moi je vais bien", "Médecine générale"),
    ("Pas de fièvre, pas de toux, juste une visite de routine", "Médecine générale"),
]


# --- entraînement et évaluation -------------------------------------------------------------------------------------

def mesurer(modele_entraine, jeu):
    """Précision, F1 par spécialité et matrice de confusion sur un jeu [(texte, spécialité)]."""
    textes, vrais = [t for t, _ in jeu], np.array([s for _, s in jeu])
    predits = modele_entraine.predict(textes)
    classes = list(modele_entraine.classes_)
    f1 = f1_score(vrais, predits, labels=classes, average=None, zero_division=0)
    return {
        "n": len(jeu),
        "precision": round(float((predits == vrais).mean()), 4),
        "reference_toujours_la_meme_reponse": round(float(max((vrais == c).mean() for c in classes)), 4),
        "f1_par_specialite": {c: round(float(v), 3) for c, v in zip(classes, f1)},
        "f1_moyen": round(float(np.mean(f1)), 4),
        "classes": classes,
        "matrice": [[int(((vrais == v) & (predits == p)).sum()) for p in classes] for v in classes],
    }


def entrainer(n=TAILLE_ENTRAINEMENT, graine=1, n_test=TAILLE_TEST):
    """Entraîne le modèle et l'évalue : (modèle, évaluation). Deux jeux de test : généré (autre graine) et écrit à la main."""
    entrainement = generer(n, graine)
    entraine = modele.construire()
    entraine.fit([t for t, _ in entrainement], [s for _, s in entrainement])
    evaluation = {
        "graine": graine,
        "n_entrainement": n,
        "specialites": CLASSES,
        "seuil_par_defaut": SEUIL_PAR_DEFAUT,
        "test_genere": mesurer(entraine, generer(n_test, graine + 1000)),
        "test_a_la_main": mesurer(entraine, PHRASES_A_LA_MAIN),
    }
    return entraine, evaluation


def sauvegarder(entraine, evaluation, dossier=None):
    dossier = Path(dossier or DOSSIER_ARTEFACTS)
    dossier.mkdir(parents=True, exist_ok=True)
    joblib.dump(entraine, dossier / NOM_MODELE, compress=3)
    (dossier / NOM_EVALUATION).write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")


def charger_evaluation(dossier=None):
    try:
        return json.loads((Path(dossier or DOSSIER_ARTEFACTS) / NOM_EVALUATION).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def charger():
    """Le modèle prêt à servir, ou None. Chargé une seule fois ; entraîné puis enregistré s'il n'existe pas encore."""
    with _verrou:
        if _etat["modele"] is not None or _etat["tente"]:
            return _etat["modele"]
        _etat["tente"] = True
        chemin = DOSSIER_ARTEFACTS / NOM_MODELE
        try:
            if chemin.exists():
                try:
                    _etat["modele"] = joblib.load(chemin)
                except Exception:  # noqa: BLE001 - autre version de scikit-learn, fichier abîmé : on réentraîne (quelques secondes)
                    journal.warning("Modèle d'orientation enregistré illisible : réentraînement", exc_info=True)
                    entraine, evaluation = entrainer()
                    sauvegarder(entraine, evaluation)
                    _etat["modele"] = entraine
            else:
                entraine, evaluation = entrainer()
                sauvegarder(entraine, evaluation)
                _etat["modele"] = entraine
        except Exception:  # noqa: BLE001 - une panne ne doit jamais empêcher d'afficher les médecins
            journal.exception("Modèle d'orientation indisponible")
            _etat["modele"] = None
        return _etat["modele"]


def installer(entraine):
    with _verrou:
        _etat["modele"], _etat["tente"] = entraine, entraine is not None


def oublier():
    with _verrou:
        _etat["modele"], _etat["tente"] = None, False


def predire(texte):
    """{specialite, confiance, probas (les 3 premières), mots} pour un texte, ou None (texte vide, modèle indisponible)."""
    texte = (texte or "").strip()
    entraine = charger() if texte else None
    if entraine is None:
        return None
    try:
        probas = entraine.predict_proba([texte])[0]
        classes = [str(c) for c in entraine.classes_]
        ordre = np.argsort(probas)[::-1]
        i = int(ordre[0])
        return {
            "specialite": classes[i],
            "confiance": round(float(probas[i]), 4),
            "probas": {classes[j]: round(float(probas[j]), 4) for j in ordre[:3]},
            "mots": modele.mots_influents(entraine, texte, entraine.classes_[i]),
        }
    except Exception:  # noqa: BLE001
        journal.exception("Orientation impossible")
        return None


def conseiller(prediction, seuil=SEUIL_PAR_DEFAUT):
    """(spécialité conseillée, sûr ?). Sous le seuil de confiance, on ne devine pas : médecine générale."""
    if not prediction:
        return ls.MEDECINE_GENERALE, False
    if prediction["confiance"] >= seuil:
        return prediction["specialite"], True
    return ls.MEDECINE_GENERALE, False
