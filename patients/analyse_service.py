"""Prépare les données d'un patient pour l'analyse automatique de son dossier (lecture seule)."""
from django.utils import timezone

from . import analyse_dossier, dossier as synthese
from .models import Allergie, DossierMedical, Mesure


def analyser_patient(patient, maintenant=None):
    fiche = DossierMedical.objects.filter(patient=patient).first()
    allergies = [
        {"substance": a.substance, "gravite": a.gravite, "active": a.active}
        for a in Allergie.objects.filter(patient=patient)
    ]
    mesures = [
        {"type": m.type, "valeur": m.valeur, "valeur2": m.valeur2, "mesure_le": m.mesure_le}
        for m in Mesure.objects.filter(patient=patient)
    ]
    return analyse_dossier.analyser(
        age=patient.age,
        sexe=patient.sexe,
        groupe_sanguin=fiche.groupe_sanguin if fiche else "",
        antecedents=fiche.antecedents if fiche else "",
        traitements=fiche.traitements_en_cours if fiche else "",
        allergies=allergies,
        mesures=mesures,
        manquants=synthese.elements_manquants(patient, fiche),
        total_controles=len(synthese.CONTROLES),
        maintenant=maintenant or timezone.now(),
    )
