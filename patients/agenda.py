"""Agenda prévisionnel d'un médecin : l'heure prévue de CHAQUE patient en attente (logique pure, sans base de données).

Deux sortes de demandes se partagent le temps du médecin :
* les rendez-vous fixés (un créneau choisi) : jamais avant leur heure, mais ils peuvent être retardés ;
* la file (pas de créneau), déjà triée par `file_attente.cle_de_passage`.

On déroule la journée du médecin, consultation après consultation. À chaque instant :
1. un cas prioritaire (niveau 1 ou 2, ou demande protégée) passe d'abord, même s'il décale un rendez-vous fixé ;
2. sinon, un rendez-vous fixé dont l'heure est arrivée passe ;
3. sinon, la file passe, mais seulement si la consultation tient avant le prochain rendez-vous fixé ;
4. sinon, on attend l'heure du prochain rendez-vous.

Le retard d'une urgence se transmet donc aux rendez-vous suivants, et il s'efface quand l'agenda a un trou.
Les durées sont des minutes de PRÉSENCE du médecin (voir file_attente.ajouter_minutes_ouvrees).
"""
import datetime
from dataclasses import dataclass

from .file_attente import ajouter_minutes_ouvrees

SEUIL_ANNONCE_MIN = 10  # un patient n'est reprévenu que si son heure prévue bouge d'au moins ce nombre de minutes
SEUIL_ANNONCE_FILE_MIN = 30  # la file n'est qu'une estimation : on ne reprévient un patient de la file que pour un gros écart


@dataclass(frozen=True)
class Element:
    identifiant: object
    creneau: datetime.datetime | None = None  # heure fixée ; None : demande de la file
    prioritaire: bool = False  # peut décaler un rendez-vous fixé (niveau 1 ou 2, ou demande protégée)


def heures_prevues(maintenant, elements, duree_min, horaires, fuseau):
    """{identifiant: heure prévue} pour les demandes d'un médecin. `elements` : la file DANS SON ORDRE, puis les
    rendez-vous fixés (dans n'importe quel ordre). `duree_min` : durée d'une consultation, en minutes de présence."""
    file = [e for e in elements if e.creneau is None]
    rdv = sorted((e for e in elements if e.creneau is not None), key=lambda e: e.creneau)

    def avancer(instant, minutes):
        return ajouter_minutes_ouvrees(instant, minutes, horaires, fuseau)

    prevues, curseur = {}, maintenant
    for _ in range(3 * len(elements) + 5):  # garde-fou : chaque tour traite une demande ou saute à un rendez-vous
        if not (file or rdv):
            break
        curseur = avancer(curseur, 0)  # on se place dans les heures de présence du médecin
        tete = file[0] if file else None
        suivant = rdv[0] if rdv else None
        arrive = suivant is not None and suivant.creneau <= curseur
        tient = suivant is None or avancer(curseur, duree_min) <= suivant.creneau
        prioritaire = next((e for e in file if e.prioritaire), None)

        if tete is not None and not arrive and tient:
            choix = tete  # la file passe : aucun rendez-vous n'attend, et la consultation tient avant le suivant
        else:
            choix = prioritaire  # sinon seul un cas prioritaire peut décaler un rendez-vous fixé (ou None)

        if choix is not None:
            file.remove(choix)
        elif arrive:
            choix = rdv.pop(0)
        else:  # rien ne peut passer avant le prochain rendez-vous : on attend son heure
            curseur = suivant.creneau
            continue
        prevues[choix.identifiant] = curseur
        curseur = avancer(curseur, duree_min)
    return prevues


def retard_minutes(creneau, prevue):
    """Retard annoncé d'un rendez-vous fixé, en minutes entières (jamais négatif)."""
    return max(0, int(round((prevue - creneau).total_seconds() / 60)))


def changement_a_annoncer(creneau, annoncee, prevue, maintenant, seuil=SEUIL_ANNONCE_MIN):
    """Faut-il reprévenir le patient ? `annoncee` : dernière heure qu'on lui a communiquée (None : l'heure fixée).
    Pas de message pour un rendez-vous déjà dépassé : l'application affiche alors « en retard »."""
    if creneau <= maintenant:
        return False
    reference = annoncee or creneau
    return abs((prevue - reference).total_seconds()) >= seuil * 60


def changement_file_a_annoncer(annoncee, prevue, seuil=SEUIL_ANNONCE_FILE_MIN):
    """Faut-il reprévenir un patient de la FILE ? `annoncee` : dernière estimation qu'on lui a communiquée
    (None : il n'a pas encore été prévenu que sa demande est dans la file, donc rien à corriger)."""
    if annoncee is None:
        return False
    return abs((prevue - annoncee).total_seconds()) >= seuil * 60
