"""Tournée du jour : un ordre de passage qui limite les trajets (logique pure, sans base).

Sans coordonnées GPS, on agit sur ce qui coûte le plus de temps à un infirmier à domicile : changer de ville.
1. on commence par la ville d'exercice de l'infirmier, puis les autres villes dans l'ordre de leur premier passage ;
2. dans chaque ville, les patients prioritaires (dernier compte rendu « à signaler ») passent d'abord, puis l'ordre actuel ;
3. les heures s'enchaînent : DUREE_PASSAGE par patient, plus TRAJET_ENTRE_VILLES à chaque changement de ville.
Ce sont des estimations : l'infirmier voit la proposition et décide de l'appliquer ou non.
"""
import datetime
from dataclasses import dataclass

from .models import DUREE_PASSAGE

TRAJET_ENTRE_VILLES = datetime.timedelta(minutes=30)


def _ville(passage):
    return " ".join((passage.ville or "").split()).casefold()


@dataclass
class Tournee:
    etapes: list  # [(passage, heure)]

    @property
    def changements_de_ville(self):
        villes = [_ville(p) for p, _ in self.etapes]
        return sum(1 for a, b in zip(villes, villes[1:]) if a != b)

    @property
    def minutes_de_trajet(self):
        """Temps passé sur la route, estimé : le planning actuel ne le compte pas, la proposition oui."""
        return self.changements_de_ville * int(TRAJET_ENTRE_VILLES.total_seconds() // 60)

    @property
    def fin(self):
        return self.etapes[-1][1] + DUREE_PASSAGE if self.etapes else None


def actuelle(passages):
    """La tournée telle qu'elle est planifiée (passages dans l'ordre de leur heure)."""
    return Tournee([(p, p.date_prevue) for p in sorted(passages, key=lambda p: p.date_prevue)])


def proposer(passages, ville_depart, debut, prioritaires=()):
    """Tournée proposée à partir de `debut` (date et heure). `prioritaires` : identifiants des passages à voir d'abord."""
    passages = sorted(passages, key=lambda p: p.date_prevue)
    par_ville = {}
    for p in passages:
        par_ville.setdefault(_ville(p), []).append(p)
    depart = " ".join((ville_depart or "").split()).casefold()
    villes = sorted(par_ville, key=lambda v: (v != depart, par_ville[v][0].date_prevue))

    etapes, heure, precedente = [], debut, None
    for ville in villes:
        for p in sorted(par_ville[ville], key=lambda p: (p.pk not in prioritaires, p.date_prevue)):
            if precedente is not None and ville != precedente:
                heure += TRAJET_ENTRE_VILLES
            etapes.append((p, heure))
            heure += DUREE_PASSAGE
            precedente = ville
    return Tournee(etapes)


def est_identique(a, b):
    return [(p.pk, h) for p, h in a.etapes] == [(p.pk, h) for p, h in b.etapes]
