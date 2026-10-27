# Charge Celery avec Django, pour que les tâches (@shared_task) utilisent cette application.
from .celery import app as celery_app

__all__ = ("celery_app",)
