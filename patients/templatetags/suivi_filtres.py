from django import template

from patients import file_attente

register = template.Library()

CLASSES = {
    file_attente.DANS_LES_TEMPS: "sev-legere",
    file_attente.A_RISQUE: "sev-moderee",
    file_attente.EN_RETARD: "sev-severe",
    file_attente.PLANIFIE: "sev-info",
    file_attente.IMMEDIAT: "sev-severe",
}


@register.filter
def duree(minutes):
    """450 -> « 7 h 30 »."""
    try:
        return file_attente.formater_duree(float(minutes))
    except (TypeError, ValueError):
        return ""


@register.filter
def classe_etat(etat):
    """État d'une demande -> classe de pastille (vert, jaune, rouge, bleu)."""
    return CLASSES.get(etat, "")
