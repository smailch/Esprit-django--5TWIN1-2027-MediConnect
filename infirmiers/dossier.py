"""Lien entre les soins à domicile et le dossier du patient (app patients).

* historique         : relevés précédents du patient (passages infirmiers et mesures de santé), pour l'évolution ;
* enregistrer_mesures : les constantes d'un passage terminé deviennent des mesures de santé du patient. Elles
  apparaissent dans « Mes mesures » et dans l'analyse de son dossier, comme celles qu'il saisit lui-même.
"""
import logging

from django.core.exceptions import ValidationError

from patients.models import Mesure

from .models import InterventionDomicile

journal = logging.getLogger(__name__)

# Mesure du patient -> constante du compte rendu (la tension porte aussi le second chiffre dans valeur2).
MESURES_SUIVIES = {
    Mesure.Type.TEMPERATURE: "temperature",
    Mesure.Type.TENSION: "tension_systolique",
    Mesure.Type.FREQUENCE: "frequence_cardiaque",
    Mesure.Type.SATURATION: "saturation_oxygene",
}
NOTE = "Relevé par l'infirmier {infirmier} lors d'un soin à domicile"


def _a_la_minute(instant):
    return instant.replace(second=0, microsecond=0)


def historique(intervention):
    """[{constante: valeur}] du plus ancien au plus récent, sans la présente intervention.

    Les relevés pris à la même minute sont fusionnés : un passage infirmier et la mesure de santé qui en a été
    tirée ne comptent qu'une fois (sinon deux valeurs égales casseraient la détection d'une hausse)."""
    releves = {}

    def ajouter(instant, valeurs):
        releves.setdefault(_a_la_minute(instant), {}).update(valeurs)

    passages = InterventionDomicile.objects.filter(
        patient=intervention.patient, statut=InterventionDomicile.Statut.REALISEE
    ).exclude(pk=intervention.pk)
    for passage in passages:
        if passage.realisee_le and passage.constantes is not None:
            ajouter(passage.realisee_le, passage.releves())
    for m in Mesure.objects.filter(patient=intervention.patient, type__in=list(MESURES_SUIVIES)):
        valeurs = {MESURES_SUIVIES[m.type]: m.valeur}
        if m.type == Mesure.Type.TENSION and m.valeur2 is not None:
            valeurs["tension_diastolique"] = m.valeur2
        ajouter(m.mesure_le, valeurs)
    return [releves[instant] for instant in sorted(releves)]


def mesures_du_passage(intervention):
    """Mesures de santé (non enregistrées) tirées des constantes d'un passage terminé."""
    releves = intervention.releves()
    if intervention.statut != InterventionDomicile.Statut.REALISEE or not releves or not intervention.realisee_le:
        return []
    note = NOTE.format(infirmier=intervention.infirmier or "")[:200]
    quand = _a_la_minute(intervention.realisee_le)
    mesures = []
    for type_, nom in MESURES_SUIVIES.items():
        if nom not in releves:
            continue
        valeur2 = releves.get("tension_diastolique") if type_ == Mesure.Type.TENSION else None
        if type_ == Mesure.Type.TENSION and valeur2 is None:
            continue  # une tension sans son second chiffre n'est pas une mesure complète
        mesures.append(Mesure(patient=intervention.patient, type=type_, valeur=releves[nom], valeur2=valeur2, mesure_le=quand, note=note))
    return mesures


def enregistrer_mesures(intervention):
    """Enregistre les mesures du passage ; renvoie leur nombre. Une mesure invalide ou déjà présente à la même minute
    est ignorée, et rien ne bloque jamais la clôture du soin."""
    enregistrees = 0
    for mesure in mesures_du_passage(intervention):
        try:
            mesure.full_clean()
            mesure.save()
            enregistrees += 1
        except ValidationError as erreur:
            journal.info("Mesure %s non reprise dans le dossier (intervention %s) : %s", mesure.type, intervention.pk, erreur.messages)
    return enregistrees
