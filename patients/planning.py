"""Créneaux de rendez-vous : génération et vérification (logique pure, sans base de données).

Un médecin a des horaires par jour de semaine ({0: [(9, 12), (14, 17)], ...}, lundi = 0, heures pleines).
Les créneaux durent DUREE_MINUTES. Le patient ne peut réserver qu'à partir de DELAI_MIN_HEURES et jusqu'à
HORIZON_JOURS jours. Les cas très urgents (niveaux 1 et 2) ne réservent pas : ils passent en priorité.
"""
import datetime

DUREE_MINUTES = 30
DELAI_MIN_HEURES = 2
HORIZON_JOURS = 14
NIVEAU_MIN_RESERVATION = 3  # les niveaux 1 et 2 sont pris en charge en priorité, sans créneau fixé


def reservable(statut, niveau):
    """Un créneau se choisit pour une demande en attente, de niveau 3 à 5."""
    return statut == "en_attente" and niveau is not None and niveau >= NIVEAU_MIN_RESERVATION


def generer(horaires, maintenant, pris=()):
    """Créneaux libres, du plus proche au plus lointain (datetimes aware, fuseau de `maintenant`).

    horaires  : {jour_de_semaine: [(heure_debut, heure_fin), ...]}.
    maintenant: datetime aware (heure locale).
    pris      : créneaux déjà réservés chez ce médecin.
    """
    pris = set(pris)
    premier = maintenant + datetime.timedelta(hours=DELAI_MIN_HEURES)
    libres = []
    for decalage in range(HORIZON_JOURS + 1):
        jour = maintenant.date() + datetime.timedelta(days=decalage)
        for debut_h, fin_h in horaires.get(jour.weekday(), []):
            instant = datetime.datetime.combine(jour, datetime.time(debut_h), tzinfo=maintenant.tzinfo)
            fin = datetime.datetime.combine(jour, datetime.time(fin_h), tzinfo=maintenant.tzinfo)
            while instant + datetime.timedelta(minutes=DUREE_MINUTES) <= fin:
                if instant >= premier and instant not in pris:
                    libres.append(instant)
                instant += datetime.timedelta(minutes=DUREE_MINUTES)
    return libres


def lire_choix(texte, fuseau):
    """Date envoyée par le formulaire (ISO 8601) -> datetime aware, ou None si illisible."""
    try:
        valeur = datetime.datetime.fromisoformat((texte or "").strip())
    except ValueError:
        return None
    return valeur if valeur.tzinfo else valeur.replace(tzinfo=fuseau)


def periode(instant):
    if instant.hour < 12:
        return "Matin"
    return "Après-midi" if instant.hour < 18 else "Soir"


def grouper(libres):
    """Créneaux regroupés par jour puis par moment de la journée, pour l'affichage."""
    jours = []
    for instant in libres:
        if not jours or jours[-1]["jour"] != instant.date():
            jours.append({"jour": instant.date(), "total": 0, "groupes": []})
        jour = jours[-1]
        jour["total"] += 1
        nom = periode(instant)
        if not jour["groupes"] or jour["groupes"][-1]["nom"] != nom:
            jour["groupes"].append({"nom": nom, "creneaux": []})
        jour["groupes"][-1]["creneaux"].append(instant)
    return jours


def grille(horaires, maintenant, pris=()):
    """Tous les créneaux de la période, libres ou déjà pris : [(instant, libre)]."""
    pris = set(pris)
    return [(c, c not in pris) for c in generer(horaires, maintenant)]


def grouper_grille(grille_creneaux):
    """Grille regroupée par jour puis par moment de la journée. Les créneaux pris restent visibles
    (grisés) pour que le patient comprenne pourquoi ils ne sont pas proposés."""
    jours = []
    for instant, libre in grille_creneaux:
        if not jours or jours[-1]["jour"] != instant.date():
            jours.append({"jour": instant.date(), "total": 0, "groupes": []})
        jour = jours[-1]
        if libre:
            jour["total"] += 1
        nom = periode(instant)
        if not jour["groupes"] or jour["groupes"][-1]["nom"] != nom:
            jour["groupes"].append({"nom": nom, "creneaux": []})
        jour["groupes"][-1]["creneaux"].append({"debut": instant, "libre": libre})
    return jours
