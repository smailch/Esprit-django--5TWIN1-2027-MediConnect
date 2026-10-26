"""Évaluation de la détection des signes d'alerte dans les comptes rendus de soin (règles seules, puis règles + IA).

Métriques d'une classification à trois niveaux (ras, surveiller, signaler) : exactitude, précision, rappel et F1 par
niveau, F1 macro, matrice de confusion, et deux chiffres de sécurité : les alertes manquées (une note « à signaler »
classée RAS) et les fausses alertes (une note RAS classée « à signaler »). Pour l'IA : temps de réponse par note.
"""
import json
import statistics
import time
from pathlib import Path

NIVEAUX = ("ras", "surveiller", "signaler")
CORPUS = Path(__file__).resolve().parent / "notes_annotees.json"
RESULTATS = Path(__file__).resolve().parent / "resultats.json"


def charger(chemin=CORPUS):
    return json.loads(Path(chemin).read_text(encoding="utf-8"))["notes"]


def metriques(vrais, predits):
    matrice = [[sum(1 for v, p in zip(vrais, predits) if v == a and p == b) for b in NIVEAUX] for a in NIVEAUX]
    par_niveau = {}
    for i, niveau in enumerate(NIVEAUX):
        vp = matrice[i][i]
        predits_n = sum(matrice[j][i] for j in range(len(NIVEAUX)))
        reels_n = sum(matrice[i])
        precision = vp / predits_n if predits_n else 0.0
        rappel = vp / reels_n if reels_n else 0.0
        f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0.0
        par_niveau[niveau] = {"precision": round(precision, 3), "rappel": round(rappel, 3), "f1": round(f1, 3), "support": reels_n}
    n = len(vrais)
    return {
        "n": n,
        "exactitude": round(sum(1 for v, p in zip(vrais, predits) if v == p) / n, 3) if n else 0.0,
        "f1_macro": round(statistics.mean(m["f1"] for m in par_niveau.values()), 3),
        "par_niveau": par_niveau,
        "matrice": {"lignes = attendu, colonnes = prédit": list(NIVEAUX), "valeurs": matrice},
        "alertes_manquees": sum(1 for v, p in zip(vrais, predits) if v == "signaler" and p == "ras"),
        "fausses_alertes": sum(1 for v, p in zip(vrais, predits) if v == "ras" and p == "signaler"),
    }


def evaluer(notes, analyser, avec_ia=False, pause=0.0, essais=3):
    """analyser(texte, utiliser_ia) -> objet avec .niveau et .statut_ia. Renvoie les métriques et le détail.

    pause : secondes entre deux appels à l'IA (offre gratuite limitée en requêtes par minute) ; une réponse « limite »
    est retentée après une attente plus longue. Le temps mesuré est celui de l'appel qui aboutit, attente exclue."""
    vrais, predits, durees, statuts, detail = [], [], [], {}, []
    for note in notes:
        for essai in range(essais if avec_ia else 1):
            if avec_ia and pause:
                time.sleep(pause * (1 if essai == 0 else 8))
            debut = time.perf_counter()
            analyse = analyser(note["texte"], avec_ia)
            duree = (time.perf_counter() - debut) * 1000
            if getattr(analyse, "statut_ia", "") != "limite":
                break
        vrais.append(note["attendu"])
        predits.append(analyse.niveau)
        if avec_ia:
            durees.append(duree)
            statuts[analyse.statut_ia] = statuts.get(analyse.statut_ia, 0) + 1
        detail.append({"texte": note["texte"], "attendu": note["attendu"], "predit": analyse.niveau})
    resultat = metriques(vrais, predits)
    if avec_ia:
        durees.sort()
        resultat["temps_ms"] = {
            "moyenne": round(statistics.mean(durees)), "mediane": round(statistics.median(durees)),
            "p95": round(durees[min(len(durees) - 1, int(0.95 * len(durees)))]), "max": round(durees[-1]),
        }
        resultat["statuts_ia"] = statuts
    resultat["erreurs"] = [d for d in detail if d["attendu"] != d["predit"]]
    return resultat
