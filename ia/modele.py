"""Le modèle qui lit le texte libre d'un patient et estime son niveau d'urgence (1 à 5).

Un modèle d'apprentissage automatique classique et léger (scikit-learn) : on transforme le texte en chiffres
(TF-IDF sur les mots et sur les groupes de lettres, ce qui le rend tolérant aux fautes de frappe), puis une
régression logistique donne une probabilité par niveau. Quelques Mo, aucun GPU, rien à télécharger.

Il est entraîné sur un jeu SYNTHÉTIQUE (voir donnees.py) : c'est un prototype. Il ne pose aucun diagnostic et ne sert
qu'à RELEVER l'urgence (voir decision.py) ; le médecin garde la décision.
"""
import json
import logging
import threading
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from . import donnees

journal = logging.getLogger("mediconnect.ia")

DOSSIER_ARTEFACTS = Path(__file__).resolve().parent / "artefacts"
NOM_MODELE, NOM_EVALUATION = "triage_texte.joblib", "evaluation.json"
NIVEAUX = (1, 2, 3, 4, 5)
TAILLE_ENTRAINEMENT, TAILLE_TEST = 6000, 1500

_verrou = threading.Lock()
_etat = {"modele": None, "tente": False}


def construire():
    """Le modèle, non entraîné."""
    mots = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), strip_accents="unicode", lowercase=True, sublinear_tf=True, min_df=2)
    lettres = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), strip_accents="unicode", lowercase=True, sublinear_tf=True, min_df=3)
    return Pipeline([
        ("vec", FeatureUnion([("mots", mots), ("lettres", lettres)])),
        ("clf", LogisticRegression(max_iter=2000, C=10, class_weight="balanced")),
    ])


# --- évaluation ---------------------------------------------------------------------------------------------------

def mesurer(modele, jeu):
    """Précision et sécurité du modèle sur un jeu [(texte, niveau)]."""
    textes, vrais = [t for t, _ in jeu], np.array([n for _, n in jeu])
    predits = modele.predict(textes)
    matrice = [[int(((vrais == v) & (predits == p)).sum()) for p in NIVEAUX] for v in NIVEAUX]
    graves, calmes = vrais <= 2, vrais >= 4
    return {
        "n": len(jeu),
        "precision": round(float((predits == vrais).mean()), 4),
        "a_un_niveau_pres": round(float((abs(predits - vrais) <= 1).mean()), 4),
        # cas réellement graves (niveaux 1-2) : le modèle les voit-il, ou les prend-il pour bénins ?
        "graves_reperes": round(float((predits[graves] <= 2).mean()), 4) if graves.any() else None,
        "graves_pris_pour_benins": round(float((predits[graves] >= 4).mean()), 4) if graves.any() else None,
        # cas réellement bénins (niveaux 4-5) pris pour des urgences : ce sont les fausses alertes
        "fausses_alertes": round(float((predits[calmes] <= 2).mean()), 4) if calmes.any() else None,
        "reference_toujours_la_meme_reponse": round(float(max((vrais == n).mean() for n in NIVEAUX)), 4),
        "repartition": {str(n): int((vrais == n).sum()) for n in NIVEAUX},
        "matrice": matrice,
    }


def entrainer(n=TAILLE_ENTRAINEMENT, graine=1, n_test=TAILLE_TEST):
    """Entraîne le modèle et l'évalue. Renvoie (modèle, évaluation). Deux jeux de test :
    des phrases générées (autre graine que l'entraînement) et des phrases écrites à la main, hors du lexique."""
    entrainement = donnees.generer(n, graine)
    modele = construire()
    modele.fit([t for t, _ in entrainement], [niv for _, niv in entrainement])
    evaluation = {
        "graine": graine,
        "n_entrainement": n,
        "repartition_entrainement": {str(v): sum(1 for _, niv in entrainement if niv == v) for v in NIVEAUX},
        "test_genere": mesurer(modele, donnees.generer(n_test, graine + 1000)),
        "test_a_la_main": mesurer(modele, donnees.phrases_a_la_main()),
        "mots_par_niveau": mots_par_niveau(modele),
    }
    return modele, evaluation


# --- explication : quels mots ont pesé ------------------------------------------------------------------------------

def _bloc_mots(modele):
    vec = modele.named_steps["vec"].transformer_list[0][1]
    return vec, len(vec.vocabulary_)


def mots_par_niveau(modele, n=8):
    """Les mots les plus associés à chaque niveau d'urgence (les plus gros coefficients)."""
    vec, taille = _bloc_mots(modele)
    noms, clf = vec.get_feature_names_out(), modele.named_steps["clf"]
    return {
        str(int(niveau)): [str(noms[i]) for i in np.argsort(clf.coef_[ligne][:taille])[::-1][:n]]
        for ligne, niveau in enumerate(clf.classes_)
    }


def mots_influents(modele, texte, niveau, n=4):
    """Les mots de ce texte qui poussent le plus vers ce niveau."""
    vec, taille = _bloc_mots(modele)
    clf = modele.named_steps["clf"]
    ligne = list(clf.classes_).index(niveau)
    x = vec.transform([texte]).tocoo()
    poids = sorted(((v * clf.coef_[ligne][c], c) for v, c in zip(x.data, x.col)), reverse=True)
    noms = vec.get_feature_names_out()
    return [str(noms[c]) for p, c in poids[:n] if p > 0]


# --- sauvegarde et chargement ---------------------------------------------------------------------------------------

def sauvegarder(modele, evaluation, dossier=None):
    dossier = Path(dossier or DOSSIER_ARTEFACTS)
    dossier.mkdir(parents=True, exist_ok=True)
    joblib.dump(modele, dossier / NOM_MODELE, compress=3)
    (dossier / NOM_EVALUATION).write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")


def charger_evaluation(dossier=None):
    chemin = Path(dossier or DOSSIER_ARTEFACTS) / NOM_EVALUATION
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def charger():
    """Le modèle prêt à servir, ou None s'il est inutilisable. Chargé une seule fois ; s'il n'existe pas encore,
    il est entraîné (quelques secondes) puis enregistré. Une panne ne doit jamais empêcher un triage."""
    with _verrou:
        if _etat["modele"] is not None or _etat["tente"]:
            return _etat["modele"]
        _etat["tente"] = True
        chemin = DOSSIER_ARTEFACTS / NOM_MODELE
        try:
            if chemin.exists():
                _etat["modele"] = joblib.load(chemin)
            else:
                modele, evaluation = entrainer()
                sauvegarder(modele, evaluation)
                _etat["modele"] = modele
        except Exception:  # noqa: BLE001 - quoi qu'il arrive, le triage continue avec ses règles
            journal.exception("Modèle de lecture du texte indisponible")
            _etat["modele"] = None
        return _etat["modele"]


def installer(modele):
    """Remplace le modèle en mémoire (après un réentraînement, ou dans les tests)."""
    with _verrou:
        _etat["modele"], _etat["tente"] = modele, modele is not None


def oublier():
    with _verrou:
        _etat["modele"], _etat["tente"] = None, False


def predire(texte):
    """{niveau, confiance, probas, mots} pour un texte, ou None (texte vide, modèle indisponible)."""
    texte = (texte or "").strip()
    if not texte:
        return None
    modele = charger()
    if modele is None:
        return None
    try:
        probas = modele.predict_proba([texte])[0]
        classes = [int(c) for c in modele.classes_]
        i = int(np.argmax(probas))
        return {
            "niveau": classes[i],
            "confiance": round(float(probas[i]), 4),
            "probas": {str(c): round(float(p), 4) for c, p in zip(classes, probas)},
            "mots": mots_influents(modele, texte, classes[i]),
        }
    except Exception:  # noqa: BLE001
        journal.exception("Lecture du texte impossible")
        return None
