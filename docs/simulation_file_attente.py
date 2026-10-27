"""Simulation de la file d'attente avec le code réel du projet.

Compare l'ancienne règle (niveau, puis arrivée) à la file équitable (échéances, plafond, garantie).
À lancer depuis la racine du projet : python docs/simulation_file_attente.py
Écrit resultats_simulation.json dans le dossier courant (ou dans le dossier de la variable SORTIE).
"""
import datetime
import json
import math
import os
import random
import statistics
import sys
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())
os.environ["DJANGO_SETTINGS_MODULE"] = "mediconnect.settings"
import django  # noqa: E402

django.setup()
from patients import file_attente as fa  # noqa: E402
from patients.models import Triage  # noqa: E402

TUNIS = datetime.timezone(datetime.timedelta(hours=1))
HORAIRES = {j: [(8, 16)] for j in range(7)}  # 8 h de présence par jour, 7 jours sur 7
CAPACITE_HEURE = 3  # 3 consultations par heure : 24 par jour
MIX = [(2, 0.15), (3, 0.25), (4, 0.35), (5, 0.25)]
DEBUT = datetime.datetime(2026, 1, 5, 0, 0, tzinfo=TUNIS)
JOURS = 90


def poisson(lam, rng):
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def niveau(rng):
    r, cumul = rng.random(), 0
    for n, part in MIX:
        cumul += part
        if r <= cumul:
            return n
    return 5


def simuler(regle, charge, graine=7):
    rng = random.Random(graine)
    lam_h = charge * CAPACITE_HEURE * 8 / 24
    file_, resultats = [], {n: [] for n in (2, 3, 4, 5)}
    for h in range(JOURS * 24):
        maintenant = DEBUT + datetime.timedelta(hours=h)
        for _ in range(poisson(lam_h, rng)):
            n = niveau(rng)
            file_.append(SimpleNamespace(cree_le=maintenant + datetime.timedelta(minutes=rng.randrange(60)), niveau_effectif=n,
                                         nb_depassements=0, creneau=None, pk=len(resultats) + rng.random()))
        if maintenant.hour in range(8, 16) and file_:
            fin_h = maintenant + datetime.timedelta(hours=1)
            file_ = [t for t in file_ if t.cree_le <= fin_h]
            if regle == "ancienne":
                ordre = sorted(file_, key=lambda t: (t.niveau_effectif, t.cree_le))
            else:
                ordre = Triage.trier_file(file_, fa.DEFAUT, HORAIRES, maintenant)
            for _ in range(CAPACITE_HEURE):
                if not ordre:
                    break
                vu = ordre.pop(0)
                file_.remove(vu)
                if regle != "ancienne":  # comptage des dépassements, comme le back-office
                    for pk in fa.depassees_par((vu.cree_le, None), [(t.pk, t.cree_le, None) for t in file_]):
                        for t in file_:
                            if t.pk == pk:
                                t.nb_depassements += 1
                attente_h = max(0, (maintenant - vu.cree_le).total_seconds() / 3600)
                presence = fa.minutes_ouvrees_entre(vu.cree_le, maintenant, HORAIRES, TUNIS)
                resultats[vu.niveau_effectif].append((attente_h, presence))
    fin = DEBUT + datetime.timedelta(days=JOURS)
    restantes = len(file_)
    plus_ancienne = max(((fin - t.cree_le).total_seconds() / 86400 for t in file_), default=0)
    return resultats, restantes, plus_ancienne


sortie = {}
for charge in (0.85, 0.95, 1.00, 1.05):
    sortie[str(charge)] = {}
    for regle in ("ancienne", "equitable"):
        res, restantes, ancienne = simuler(regle, charge)
        lignes = {}
        for n, valeurs in res.items():
            if not valeurs:
                continue
            att = sorted(v[0] for v in valeurs)
            hors = 100 * sum(1 for _, pres in valeurs if pres > fa.DEFAUT.delais[n]) / len(valeurs)
            lignes[n] = {"vus": len(valeurs), "moyenne_h": round(statistics.mean(att), 1), "p95_h": round(att[int(.95 * len(att)) - 1], 1),
                         "max_h": round(max(att), 1), "hors_delai_pct": round(hors, 1)}
        sortie[str(charge)][regle] = {"niveaux": lignes, "restantes": restantes, "plus_ancienne_jours": round(ancienne, 1)}
        print(f"charge {int(charge*100)}% {regle}: niveau 5 -> {lignes.get(5)} | restantes {restantes}, plus ancienne {ancienne:.1f} j", flush=True)
json.dump(sortie, open(os.path.join(os.environ.get("SORTIE", "."), "resultats_simulation.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
