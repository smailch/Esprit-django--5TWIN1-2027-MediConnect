"""File d'attente équitable : échéances par niveau, plafond de dépassements, attente estimée.

Logique pure (sans base de données). Principe :

* chaque demande reçoit une ÉCHÉANCE = heure de la demande + délai cible de son niveau, comptée en
  temps de présence du médecin (un patient arrivé la nuit n'est pas « en retard » à son réveil) ;
* la file est triée par échéance croissante : un cas urgent passe devant, mais un patient ancien
  finit toujours par devenir le plus pressé (aucune « famine ») ;
* les niveaux 2 et 3 restent prioritaires ; un patient de niveau 4 ou 5 ne peut être dépassé qu'un nombre
  limité de fois (plafond) par des demandes moins anciennes de même rang ;
* filet de sécurité : une demande protégée qui a attendu N fois son délai cible (3 par défaut) passe
  même devant les cas urgents. Aucune demande n'attend donc indéfiniment ;
* un créneau réservé est un engagement : il sort de la file (voie « planifiée »).

Les délais sont des valeurs de démonstration, à faire valider par un professionnel de santé.
"""
import datetime
from dataclasses import dataclass

NIVEAU_VITAL = 1
NIVEAUX_AVEC_DELAI = (2, 3, 4, 5)
NIVEAU_MAX_PRIORITAIRE = 3  # les niveaux 2 et 3 passent avant les demandes « protégées » de niveau 4 et 5
JOURS_MAX_RECHERCHE = 800  # garde-fou : au-delà, on retombe sur le temps réel

# états d'une demande en attente
DANS_LES_TEMPS = "dans_les_temps"
A_RISQUE = "a_risque"
EN_RETARD = "en_retard"
PLANIFIE = "planifie"
IMMEDIAT = "immediat"
INCONNU = "inconnu"

LIBELLES_ETAT = {
    DANS_LES_TEMPS: "Dans les temps",
    A_RISQUE: "À risque",
    EN_RETARD: "En retard",
    PLANIFIE: "Rendez-vous fixé",
    IMMEDIAT: "Immédiat",
    INCONNU: "—",
}


@dataclass(frozen=True)
class Reglage:
    """Paramètres de la file (modifiables par l'administrateur)."""

    delais: dict  # niveau -> délai cible en minutes de présence du médecin
    plafond: int = 5  # nombre maximal de dépassements subis par une demande
    seuil_risque: float = 0.75  # part du délai écoulée à partir de laquelle la demande est « à risque »
    duree_consultation: int = 20  # minutes, pour estimer l'attente
    facteur_garantie: float = 3.0  # une demande protégée qui a attendu N fois son délai passe avant les urgents


DEFAUT = Reglage(delais={2: 30, 3: 120, 4: 480, 5: 1440})


@dataclass(frozen=True)
class Delai:
    etat: str
    echeance: datetime.datetime | None = None
    cible_min: float = 0
    ecoule_min: float = 0
    reste_min: float = 0
    ratio: float = 0

    @property
    def pourcentage(self):
        return max(0, min(100, round(self.ratio * 100)))

    @property
    def libelle(self):
        return LIBELLES_ETAT[self.etat]


# --- temps de présence du médecin -----------------------------------------------------------

def _bornes(jour, debut_h, fin_h, fuseau):
    debut = datetime.datetime.combine(jour, datetime.time(debut_h), tzinfo=fuseau)
    if fin_h >= 24:
        fin = datetime.datetime.combine(jour + datetime.timedelta(days=1), datetime.time(0), tzinfo=fuseau)
    else:
        fin = datetime.datetime.combine(jour, datetime.time(fin_h), tzinfo=fuseau)
    return debut, fin


def minutes_ouvrees_entre(debut, fin, horaires, fuseau):
    """Minutes de présence du médecin entre deux instants. Sans horaires : temps réel."""
    if fin <= debut:
        return 0.0
    if not horaires:
        return (fin - debut).total_seconds() / 60
    debut, fin = debut.astimezone(fuseau), fin.astimezone(fuseau)
    total, jour = 0.0, debut.date()
    while jour <= fin.date():
        for debut_h, fin_h in sorted(horaires.get(jour.weekday(), [])):
            a, b = _bornes(jour, debut_h, fin_h, fuseau)
            total += max(0.0, (min(b, fin) - max(a, debut)).total_seconds() / 60)
        jour += datetime.timedelta(days=1)
    return total


def ajouter_minutes_ouvrees(debut, minutes, horaires, fuseau):
    """Instant atteint après `minutes` de présence du médecin. Sans horaires : temps réel."""
    if not horaires:
        return debut + datetime.timedelta(minutes=minutes)
    debut = debut.astimezone(fuseau)
    reste, jour = float(minutes), debut.date()
    for _ in range(JOURS_MAX_RECHERCHE):
        for debut_h, fin_h in sorted(horaires.get(jour.weekday(), [])):
            a, b = _bornes(jour, debut_h, fin_h, fuseau)
            a = max(a, debut)
            if a >= b:
                continue
            disponible = (b - a).total_seconds() / 60
            if reste <= disponible:
                return a + datetime.timedelta(minutes=reste)
            reste -= disponible
        jour += datetime.timedelta(days=1)
    return debut + datetime.timedelta(minutes=minutes)


# --- échéance, état, ordre ------------------------------------------------------------------

def evaluer_delai(cree_le, niveau, maintenant, reglage, horaires, fuseau):
    """Échéance et état d'une demande SANS créneau, selon son niveau effectif."""
    if niveau == NIVEAU_VITAL:
        return Delai(etat=IMMEDIAT)
    if niveau not in reglage.delais:
        return Delai(etat=INCONNU)
    cible = reglage.delais[niveau]
    ecoule = minutes_ouvrees_entre(cree_le, maintenant, horaires, fuseau)
    ratio = ecoule / cible
    if ratio >= 1:
        etat = EN_RETARD
    elif ratio >= reglage.seuil_risque:
        etat = A_RISQUE
    else:
        etat = DANS_LES_TEMPS
    return Delai(
        etat=etat,
        echeance=ajouter_minutes_ouvrees(cree_le, cible, horaires, fuseau),
        cible_min=cible,
        ecoule_min=ecoule,
        reste_min=cible - ecoule,
        ratio=ratio,
    )


def delai_planifie(creneau, maintenant):
    """Une demande avec créneau est « en retard » seulement si le créneau est passé."""
    if maintenant > creneau:
        return Delai(etat=EN_RETARD, echeance=creneau)
    return Delai(etat=PLANIFIE, echeance=creneau)


def est_protege(nb_depassements, reglage):
    """Une demande dépassée trop souvent ne peut plus l'être (sauf par un cas vital)."""
    return (nb_depassements or 0) >= reglage.plafond


def cle_de_passage(niveau, nb_depassements, delai, cree_le, reglage):
    """Clé de tri de la file, par groupes (le plus petit passe d'abord), puis par échéance croissante :

    0. cas vital ;
    1. demande protégée qui a attendu au moins `facteur_garantie` fois son délai cible (garantie anti-famine) ;
    2. niveaux 2 et 3 (urgents) ;
    3. demandes protégées de niveau 4 et 5 (déjà dépassées autant que le plafond le permet) ;
    4. toutes les autres.
    """
    protegee = est_protege(nb_depassements, reglage)
    if niveau == NIVEAU_VITAL:
        groupe = 0
    elif protegee and delai.ratio >= reglage.facteur_garantie:
        groupe = 1
    elif niveau is not None and niveau <= NIVEAU_MAX_PRIORITAIRE:
        groupe = 2
    elif protegee:
        groupe = 3
    else:
        groupe = 4
    return (groupe, delai.echeance or cree_le, cree_le)


def depassees_par(prise, en_attente):
    """Demandes (de la file) qui comptent un dépassement quand `prise` est prise en charge.

    prise      : (cree_le, creneau). Une demande avec créneau ne double personne : elle a sa voie.
    en_attente : liste de (identifiant, cree_le, creneau) des autres demandes encore en attente.
    """
    cree_le, creneau = prise
    if creneau is not None:
        return []
    return [i for i, c, cr in en_attente if cr is None and c < cree_le]


def attente_estimee(position, maintenant, reglage, horaires, fuseau):
    """Instant estimé de prise en charge pour la `position`-ième demande de la file (1 = prochaine)."""
    devant = max(0, position - 1)
    return ajouter_minutes_ouvrees(maintenant, devant * reglage.duree_consultation, horaires, fuseau)


def formater_duree(minutes):
    """« 45 min », « 2 h 10 », « 24 h »."""
    minutes = int(round(abs(minutes)))
    if minutes < 60:
        return f"{minutes} min"
    heures, reste = divmod(minutes, 60)
    return f"{heures} h {reste:02d}" if reste else f"{heures} h"
