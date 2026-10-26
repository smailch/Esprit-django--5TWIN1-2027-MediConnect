"""Tâches Celery des soins à domicile : relire par l'IA un compte rendu enregistré pendant une panne de l'IA.

Quand l'infirmier enregistre son compte rendu, l'IA lit la note en même temps que les règles. Si le service d'IA ne
répond pas à ce moment-là (délai dépassé, réseau, limite du fournisseur), le compte rendu est enregistré avec l'avis
des règles seules, et cette tâche réessaie la lecture IA en arrière-plan (1 min, puis 2, puis 4). Le niveau d'alerte
ne peut que monter : un signe vu par l'IA s'ajoute, rien de ce que les règles ont vu n'est retiré.

Sans Celery (pas de REDIS_URL), la relecture n'est pas programmée : la page n'attend jamais deux fois l'IA.
"""
import logging

from celery import shared_task
from django.conf import settings

from patients import ia_client

from . import alertes, dossier, ia_soin

journal = logging.getLogger("mediconnect.ia")

PANNES_PASSAGERES = (ia_client.DELAI, ia_client.RESEAU, ia_client.LIMITE, ia_client.ERREUR_HTTP)


class IaToujoursIndisponible(Exception):
    pass


def programmer_relecture(intervention):
    """Après l'enregistrement : programme la relecture si l'IA a été indisponible (et si Celery a un courtier)."""
    if settings.CELERY_TASK_ALWAYS_EAGER or intervention.analyse_ia not in PANNES_PASSAGERES:
        return False
    try:
        relire_compte_rendu.apply_async(args=[str(intervention.pk)], countdown=60)
    except Exception:  # Redis injoignable : le compte rendu garde l'avis des règles, déjà enregistré
        journal.warning("Relecture IA non programmée (intervention %s)", intervention.pk)
        return False
    return True


@shared_task(bind=True, autoretry_for=(IaToujoursIndisponible,), retry_backoff=60, max_retries=3, time_limit=60)
def relire_compte_rendu(self, intervention_pk):
    from .models import InterventionDomicile, SigneAlerte

    intervention = (InterventionDomicile.objects.select_related("patient__user", "infirmier")
                    .filter(pk=intervention_pk, statut=InterventionDomicile.Statut.REALISEE).first())
    if intervention is None or intervention.analyse_ia == ia_client.OK:
        return "rien à faire"
    constantes = intervention.constantes
    valeurs = {n: getattr(constantes, n) for n in ("temperature", "tension_systolique", "tension_diastolique",
                                                    "frequence_cardiaque", "saturation_oxygene")} if constantes else None
    user = intervention.patient.user
    analyse = ia_soin.analyser(
        intervention.compte_rendu, constantes=valeurs, historique=dossier.historique(intervention),
        noms_patient=(user.first_name, user.last_name), identifiant=f"infirmier:{intervention.infirmier_id}",
    )
    if analyse.statut_ia in PANNES_PASSAGERES:
        raise IaToujoursIndisponible(analyse.statut_ia)
    if analyse.statut_ia != ia_client.OK:
        return analyse.statut_ia  # IA désactivée ou quota : on garde l'avis des règles

    connus = {(s.nom, s.origine) for s in intervention.signes_alerte}
    nouveaux = [s for s in analyse.signes if (s.nom, s.origine) not in connus]
    intervention.signes_alerte = list(intervention.signes_alerte) + [
        SigneAlerte(nom=s.nom, extrait=s.extrait[:200], gravite=s.gravite, origine=s.origine) for s in nouveaux
    ]
    if alertes.RANG[analyse.niveau] > alertes.RANG[intervention.niveau_alerte or alertes.RAS]:
        intervention.niveau_alerte = analyse.niveau
    intervention.analyse_ia = ia_client.OK
    intervention.save(update_fields=["signes_alerte", "niveau_alerte", "analyse_ia"])
    journal.info("Compte rendu relu par l'IA en arrière-plan : %s nouveau(x) signe(s), niveau %s (intervention %s)",
                 len(nouveaux), intervention.niveau_alerte, intervention_pk)
    return intervention.niveau_alerte
