"""Suivi de la file d'attente : annote les demandes en attente (place, délai, prise en charge estimée).

Utilisé par l'espace patient, l'espace médecin et le back-office pour que tous affichent les mêmes chiffres.
Les horaires viennent du profil `medecins.Medecin`.
"""
from django.utils import timezone

import logging

from . import agenda, file_attente, notifications, planning
from .models import ReglageTriage, Triage

journal = logging.getLogger(__name__)


def reglage_actuel():
    return ReglageTriage.actuel().vers_reglage()


def horaires_du_medecin(medecin_id):
    """Plages du médecin enregistré. Vide s'il n'existe pas, ou si ce test n'ouvre pas la base."""
    try:
        from medecins.models import Medecin
        medecin = Medecin.objects.filter(code=medecin_id).first()
    except Exception as exc:
        if exc.__class__.__name__ != "DatabaseOperationForbidden":
            raise
        return {}
    if medecin is None:
        return {}
    return medecin.horaires_planning()


def annoter(en_attente, reglage=None, maintenant=None):
    """Calcule, pour chaque demande en attente, ce qu'on affiche. Modifie les objets sur place.

    Ajoute à chaque demande : `place` ((position, total) ou None si rendez-vous fixé), `delai`
    (file_attente.Delai), `prise_en_charge_estimee` (= `heure_prevue`, voir agenda.py), `retard_min` (minutes de
    retard d'un rendez-vous fixé), `protegee`.
    Renvoie {medecin_id: {"file": [...], "planning": [...]}} : la file triée et les rendez-vous fixés.
    """
    reglage = reglage or reglage_actuel()
    maintenant = maintenant or timezone.now()
    fuseau = timezone.get_current_timezone()

    par_medecin = {}
    for t in en_attente:
        par_medecin.setdefault(t.medecin_id, []).append(t)

    resultat = {}
    for medecin_id, demandes in par_medecin.items():
        horaires = horaires_du_medecin(medecin_id)
        file = Triage.trier_file(demandes, reglage, horaires, maintenant)
        planning = sorted((t for t in demandes if t.creneau), key=lambda t: t.creneau)
        # Une seule simulation de la journée du médecin : la file et les rendez-vous fixés se partagent son temps.
        elements = [
            agenda.Element(t.pk, prioritaire=(t.niveau_effectif or 5) <= 2 or t.est_protegee(reglage)) for t in file
        ] + [agenda.Element(t.pk, creneau=t.creneau) for t in planning]
        prevues = agenda.heures_prevues(maintenant, elements, reglage.duree_consultation, horaires, fuseau)
        for position, t in enumerate(file, start=1):
            t.place = (position, len(file))
            t.delai = t.delai_calcule(reglage, horaires, maintenant)
            t.heure_prevue = t.prise_en_charge_estimee = prevues[t.pk]
            t.retard_min = 0
            t.protegee = t.est_protegee(reglage)
        for t in planning:
            t.place = None
            t.delai = t.delai_calcule(reglage, horaires, maintenant)
            t.heure_prevue = t.prise_en_charge_estimee = prevues[t.pk]
            t.retard_min = agenda.retard_minutes(t.creneau, t.heure_prevue)
            t.protegee = False
        resultat[medecin_id] = {"file": file, "planning": planning}
    return resultat


def prevenir_des_changements(medecin_id, lien_de, maintenant=None):
    """Après un événement qui bouge l'agenda d'un médecin (urgence, annulation, fin de consultation) : prévient par
    e-mail les patients dont l'heure PRÉVUE a changé d'au moins agenda.SEUIL_ANNONCE_MIN minutes. Renvoie leur nombre.

    `lien_de(triage)` donne l'adresse de la page du rendez-vous. Ne lève jamais d'erreur : un problème d'envoi ne
    doit pas empêcher l'action qui l'a déclenché."""
    maintenant = maintenant or timezone.now()
    try:
        demandes = list(Triage.objects.filter(medecin_id=medecin_id, statut=Triage.Statut.EN_ATTENTE))
        annoter(demandes, maintenant=maintenant)
        prevenus = 0
        for t in demandes:
            if t.creneau:
                a_dire = agenda.changement_a_annoncer(t.creneau, t.heure_annoncee, t.heure_prevue, maintenant)
                envoye = a_dire and notifications.rendez_vous_decale(t, t.heure_prevue, lien_de(t))
            else:  # patient de la file : seulement s'il a déjà été prévenu, et pour un gros écart
                a_dire = agenda.changement_file_a_annoncer(t.heure_annoncee, t.heure_prevue)
                envoye = a_dire and notifications.estimation_modifiee(t, t.heure_annoncee, t.heure_prevue, lien_de(t))
            if envoye:
                t.heure_annoncee = t.heure_prevue
                t.save(update_fields=["heure_annoncee"])
                prevenus += 1
        return prevenus
    except Exception:
        journal.exception("Prévenir des changements d'heure impossible (médecin %s)", medecin_id)
        return 0


def confirmer_la_file(triage, lien_de, maintenant=None):
    """Prévient le patient que sa demande est dans la file (place, heure ESTIMÉE), une seule fois. À appeler quand il
    a décidé de rester dans la file. Renvoie True si le message est parti ; ne lève jamais d'erreur."""
    maintenant = maintenant or timezone.now()
    try:
        demandes = list(Triage.objects.filter(medecin_id=triage.medecin_id, statut=Triage.Statut.EN_ATTENTE))
        annoter(demandes, maintenant=maintenant)
        t = next((d for d in demandes if d.pk == triage.pk), None)
        if t is None or t.creneau or t.heure_annoncee is not None:
            return False
        if not notifications.demande_en_file(t, t.heure_prevue, t.place, lien_de(t), planning.reservable(t.statut, t.niveau_effectif)):
            return False
        t.heure_annoncee = t.heure_prevue
        t.save(update_fields=["heure_annoncee"])
        return True
    except Exception:
        journal.exception("Confirmer la file impossible (demande %s)", triage.pk)
        return False


def toutes_les_demandes_en_attente():
    return list(Triage.objects.filter(statut=Triage.Statut.EN_ATTENTE))
