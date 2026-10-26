#!/bin/sh
# Démarrage d'un conteneur MediConnect selon SERVICE : « web » (défaut) ou « worker ».
set -e

case "${SERVICE:-web}" in
  worker)
    # Tâches de fond : e-mails de notification, analyse IA du dossier, relecture IA des comptes rendus.
    exec celery -A mediconnect worker --loglevel=info --concurrency="${CELERY_CONCURRENCE:-2}"
    ;;
  web)
    python manage.py migrate --noinput
    exec gunicorn mediconnect.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-2}" \
      --threads "${GUNICORN_THREADS:-4}" \
      --timeout 60 \
      --access-logfile - \
      --forwarded-allow-ips="*"
    ;;
  *)
    echo "SERVICE inconnu : ${SERVICE} (attendu : web ou worker)" >&2
    exit 1
    ;;
esac
