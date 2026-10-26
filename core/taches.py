"""Tâches Celery communes à toutes les apps."""
from celery import shared_task

from . import courriel


@shared_task(autoretry_for=(OSError,), retry_backoff=30, max_retries=3)
def envoyer_courriel(donnees, origine=""):
    """Envoie un e-mail de notification préparé par core.courriel.envoyer (réessaie si le réseau coupe)."""
    message = courriel.depuis_dict(donnees)
    try:
        return message.send(fail_silently=False) == 1
    except OSError:
        raise  # réseau : Celery réessaie (30 s, 60 s, 120 s)
    except Exception:
        courriel.journal.exception("Envoi de l'e-mail impossible (%s)", origine or message.subject)
        return False
