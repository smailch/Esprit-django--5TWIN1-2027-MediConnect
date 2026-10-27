"""Envoi des e-mails de notification, en tâche de fond quand Celery a un courtier (Redis).

Une notification (rendez-vous fixé, passage d'infirmier, compte rendu disponible…) ne doit jamais ralentir ni bloquer
l'action qui la déclenche : un serveur SMTP met souvent 1 à 3 s à répondre. Avec Redis, le message est confié au
worker Celery et la page répond tout de suite ; sans Redis (poste de développement, tests), il part immédiatement,
comme avant. Dans les deux cas, un échec d'envoi est journalisé et n'interrompt rien.

Le message voyage en JSON (pas de pickle) : objet, textes, destinataires et versions HTML.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

journal = logging.getLogger("mediconnect.courriel")


def vers_dict(message):
    return {
        "objet": message.subject,
        "texte": message.body,
        "de": message.from_email,
        "a": list(message.to),
        "alternatives": [[contenu, type_mime] for contenu, type_mime in getattr(message, "alternatives", [])],
    }


def depuis_dict(donnees):
    message = EmailMultiAlternatives(donnees["objet"], donnees["texte"], donnees["de"], donnees["a"])
    for contenu, type_mime in donnees["alternatives"]:
        message.attach_alternative(contenu, type_mime)
    return message


def envoyer_maintenant(message, origine="", journal=journal):
    """Envoie et renvoie True si le message est parti ; ne lève jamais d'exception."""
    try:
        return message.send(fail_silently=False) == 1
    except Exception:  # un serveur de messagerie en panne ne doit jamais empêcher l'action métier
        journal.exception("Envoi de l'e-mail impossible (%s)", origine or message.subject)
        return False


def envoyer(message, origine="", journal=journal):
    """Envoie le message, en tâche de fond si possible. Renvoie True s'il est parti (ou confié au worker).
    `journal` : le journal de l'app appelante, où l'échec d'un envoi immédiat est consigné."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return envoyer_maintenant(message, origine, journal)
    from .taches import envoyer_courriel

    try:
        envoyer_courriel.delay(vers_dict(message), origine)
    except Exception:  # Redis injoignable : on envoie quand même, dans la requête
        journal.warning("File de tâches indisponible : envoi direct de l'e-mail (%s)", origine)
        return envoyer_maintenant(message, origine, journal)
    return True
