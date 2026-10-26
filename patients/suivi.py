"""Suivi de la file d'attente : annote les demandes en attente (place, délai, prise en charge estimée).

Utilisé par l'espace patient, l'espace médecin et le back-office pour que tous affichent les mêmes chiffres.
Les horaires viennent du profil `medecins.Medecin`.
"""
from django.utils import timezone

from . import file_attente
from .models import ReglageTriage, Triage


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
    (file_attente.Delai), `prise_en_charge_estimee`, `protegee`.
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
        for position, t in enumerate(file, start=1):
            t.place = (position, len(file))
            t.delai = t.delai_calcule(reglage, horaires, maintenant)
            t.prise_en_charge_estimee = file_attente.attente_estimee(position, maintenant, reglage, horaires, fuseau)
            t.protegee = t.est_protegee(reglage)
        planning = sorted((t for t in demandes if t.creneau), key=lambda t: t.creneau)
        for t in planning:
            t.place = None
            t.delai = t.delai_calcule(reglage, horaires, maintenant)
            t.prise_en_charge_estimee = t.creneau
            t.protegee = False
        resultat[medecin_id] = {"file": file, "planning": planning}
    return resultat


def toutes_les_demandes_en_attente():
    return list(Triage.objects.filter(statut=Triage.Statut.EN_ATTENTE))
