"""Tâches Celery de l'espace patient : l'analyse IA du dossier, en arrière-plan.

L'analyse complète fait deux appels à l'IA à la suite (lecture du dossier, puis résumé en langage simple) : jusqu'à
2 × IA_DELAI_MAX secondes. Avec Celery, la page s'affiche tout de suite avec l'analyse des règles et un indicateur
« l'IA relit votre dossier » ; le worker fait les appels, leurs réponses vont dans le cache de l'IA, puis la page se
recharge et lit ce cache. Sans Celery (pas de REDIS_URL), rien ne change : l'analyse complète se fait dans la requête.

Une marque dans le cache (« en_cours », puis « fini » avec le statut) évite de lancer deux fois la même analyse et de
relancer en boucle après un échec : l'échec récent est affiché, l'analyse repartira au prochain passage (2 min).
"""
import logging
import time

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from . import analyse_service, ia_client

journal = logging.getLogger("mediconnect.ia")

DUREE_MARQUE = 300  # secondes : au-delà, une analyse « en cours » est considérée comme perdue
ATTENTE_APRES_ECHEC = 120


def _cle(patient_pk):
    return f"analyse-ia:{patient_pk}"


@shared_task(time_limit=90)
def analyser_dossier_ia(patient_pk):
    from .models import Patient

    debut = time.monotonic()
    statut = "erreur"
    try:
        patient = Patient.objects.select_related("user").filter(pk=patient_pk).first()
        if patient is not None:
            statut = analyse_service.analyser_patient(patient, ia=analyse_service.COMPLET).ia["statut"] or ia_client.OK
    except Exception:  # l'analyse des règles reste affichée ; l'erreur est journalisée
        journal.exception("Analyse IA du dossier impossible (patient %s)", patient_pk)
    duree = int((time.monotonic() - debut) * 1000)
    journal.info("Analyse IA du dossier en tâche de fond : %s en %s ms (patient %s)", statut, duree, patient_pk)
    cache.set(_cle(patient_pk), {"etat": "fini", "statut": statut, "a": time.time(), "duree_ms": duree}, DUREE_MARQUE)
    return statut


def etat(patient_pk):
    return cache.get(_cle(patient_pk)) or {}


def analyse_avec_ia_differee(patient):
    """(analyse, en_cours) : l'analyse à afficher maintenant et si l'IA travaille encore en arrière-plan."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return analyse_service.analyser_patient(patient, ia=analyse_service.COMPLET), False

    analyse = analyse_service.analyser_patient(patient, ia=analyse_service.CACHE)
    ia = analyse.ia
    if not (ia["disponible"] and ia["consentement"] and ia["contenu_a_lire"]) or ia["statut"] == ia_client.OK:
        return analyse, False  # rien à demander à l'IA, ou sa réponse est déjà en cache
    marque = etat(patient.pk)
    if marque.get("etat") == "en_cours":
        return analyse, True
    if marque.get("etat") == "fini" and marque.get("statut") != ia_client.OK and time.time() - marque["a"] < ATTENTE_APRES_ECHEC:
        ia["statut"] = marque["statut"]  # échec récent (délai, quota…) : on l'explique au lieu de relancer
        return analyse, False
    if not cache.add(_cle(patient.pk), {"etat": "en_cours", "a": time.time()}, DUREE_MARQUE) and etat(patient.pk).get("etat") == "en_cours":
        return analyse, True  # une autre requête vient de la lancer
    cache.set(_cle(patient.pk), {"etat": "en_cours", "a": time.time()}, DUREE_MARQUE)
    try:
        analyser_dossier_ia.delay(str(patient.pk))
    except Exception:  # Redis injoignable : analyse complète dans la requête, comme sans Celery
        cache.delete(_cle(patient.pk))
        journal.warning("File de tâches indisponible : analyse IA du dossier faite dans la requête")
        return analyse_service.analyser_patient(patient, ia=analyse_service.COMPLET), False
    return analyse, True
