"""Calendrier de la file : les patients déjà en attente, du plus proche au plus lointain."""

from django.utils import timezone


def par_jour(file, planning):
    """Regroupe file (heure estimée) et rendez-vous fixés (créneau), triés dans le temps.

    Chaque événement : demande, quand, heure (locale), fixe (rendez-vous choisi par le patient).
    """
    evenements = []
    for demande in planning:
        evenements.append(_evenement(demande, demande.creneau, True))
    for demande in file:
        quand = getattr(demande, "prise_en_charge_estimee", None) or demande.cree_le
        evenements.append(_evenement(demande, quand, False))
    evenements.sort(key=lambda e: e["quand"])
    jours = []
    for evenement in evenements:
        if not jours or jours[-1]["jour"] != evenement["jour"]:
            jours.append({"jour": evenement["jour"], "evenements": []})
        jours[-1]["evenements"].append(evenement)
    return jours


def _evenement(demande, quand, fixe):
    heure = timezone.localtime(quand) if quand is not None else None
    return {
        "demande": demande,
        "quand": quand or timezone.now(),
        "heure": heure,
        "jour": heure.date() if heure else None,
        "fixe": fixe,
    }
