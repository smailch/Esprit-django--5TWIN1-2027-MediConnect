"""Horaires de consultation saisis par le médecin, sous la forme « 9-12, 14-17 »."""

import re

JOURS = (
    (0, "Lundi"),
    (1, "Mardi"),
    (2, "Mercredi"),
    (3, "Jeudi"),
    (4, "Vendredi"),
    (5, "Samedi"),
    (6, "Dimanche"),
)

_PLAGE = re.compile(r"^\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*$")


def analyser_jour(texte):
    """« 9-12, 14-17 » devient [(9, 12), (14, 17)]. Un texte vide donne [].

    Lève ValueError si une plage est illisible, en dehors de 0 h–24 h, ou se chevauche.
    """
    texte = (texte or "").strip()
    if not texte:
        return []
    plages = []
    for morceau in texte.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        correspondance = _PLAGE.match(morceau)
        if not correspondance:
            raise ValueError("Écrivez les horaires sous la forme 9-12, 14-17.")
        debut, fin = int(correspondance.group(1)), int(correspondance.group(2))
        if not (0 <= debut <= 23 and 1 <= fin <= 24 and debut < fin):
            raise ValueError("Une plage doit commencer avant de finir, entre 0 h et 24 h.")
        plages.append((debut, fin))
    plages.sort()
    for (_debut, fin_precedente), (debut_suivant, _fin) in zip(plages, plages[1:]):
        if debut_suivant < fin_precedente:
            raise ValueError("Deux plages du même jour se chevauchent.")
    return plages


def texte_du_jour(plages, jour):
    """Texte affichable des plages d'un jour, prêt à être remis dans le formulaire."""
    du_jour = sorted((p.debut, p.fin) for p in plages or [] if p.jour == jour)
    return ", ".join(f"{debut}-{fin}" for debut, fin in du_jour)
