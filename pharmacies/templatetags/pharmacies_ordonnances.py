"""Balise à placer dans la page d'une consultation (module médecins) : le bouton « Envoyer l'ordonnance au patient ».

Toute la logique reste dans le module pharmacies ; la page du médecin n'a besoin que de deux lignes :
    {% load pharmacies_ordonnances %}
    {% bouton_envoi_ordonnance consultation %}
"""
from django import template

from .. import prescriptions

register = template.Library()


@register.inclusion_tag("pharmacies/_envoi_ordonnance.html", takes_context=True)
def bouton_envoi_ordonnance(context, consultation):
    deja = prescriptions.ordonnance_de(consultation)
    request = context.get("request")
    return {
        "consultation": consultation,
        "ordonnance": deja,
        # Simple présence d'un texte : l'IA n'est appelée qu'au clic, jamais à l'affichage de la page.
        "a_prescription": deja is None and prescriptions.a_une_prescription(consultation),
        "retour": request.get_full_path() if request is not None else "",
        "csrf_token": context.get("csrf_token"),
        "request": request,
    }
