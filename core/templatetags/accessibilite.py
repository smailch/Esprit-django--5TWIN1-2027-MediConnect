from django import template

register = template.Library()


@register.filter
def decrit(champ):
    """Affiche un champ de formulaire en le reliant à son aide et à ses erreurs pour les lecteurs d'écran
    (aria-describedby) et en signalant l'erreur (aria-invalid). Sans aide ni erreur, le champ est affiché tel quel."""
    attributs, ids = {}, []
    if champ.help_text:
        ids.append(f"{champ.auto_id}_aide")
    if champ.errors:
        ids.append(f"{champ.auto_id}_erreur")
        attributs["aria-invalid"] = "true"
    if ids:
        attributs["aria-describedby"] = " ".join(ids)
    return champ.as_widget(attrs=attributs) if attributs else champ
