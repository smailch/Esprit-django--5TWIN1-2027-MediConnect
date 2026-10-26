"""Application Celery de MediConnect : tâches de fond (e-mails de notification, analyses IA longues).

Lancement du worker (Redis requis, voir REDIS_URL) :  celery -A mediconnect worker -l info
Sans REDIS_URL, settings.CELERY_TASK_ALWAYS_EAGER est vrai : chaque tâche s'exécute tout de suite, dans la requête.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mediconnect.settings")

app = Celery("mediconnect")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(related_name="taches")  # le module `taches.py` de chaque app
