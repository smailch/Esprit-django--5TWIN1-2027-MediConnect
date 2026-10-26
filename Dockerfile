# Image de production de MediConnect : la même sert au site (gunicorn) et au worker Celery.
#   docker build -t mediconnect .
#   docker run -e SERVICE=web ...     -> migrations puis site (port $PORT, 8000 par défaut)
#   docker run -e SERVICE=worker ...  -> worker Celery (tâches de fond : e-mails, analyses IA)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Fichiers statiques rassemblés dans l'image (servis par WhiteNoise) ; la clé ne sert qu'à cette étape.
RUN DJANGO_SECRET_KEY=collectstatic-seulement python manage.py collectstatic --noinput \
    && chmod +x deploiement/demarrer.sh \
    && useradd --create-home --uid 1000 mediconnect \
    && chown -R mediconnect /app
USER mediconnect

EXPOSE 8000
CMD ["deploiement/demarrer.sh"]
