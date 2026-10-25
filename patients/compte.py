"""Le compte d'un patient : récupérer ses données, désactiver son compte ou le supprimer (logique, sans vue).

Partagé par l'espace patient (« Mon compte ») et l'espace administrateur (désactivation d'un patient).
"""
from django.utils import timezone

from .models import Allergie, Consultation, DossierMedical, Mesure, Patient, Triage

# Ordre de suppression : les éléments qui dépendent d'une demande avant la demande, le patient en dernier.
MODELES_DU_PATIENT = (Consultation, Triage, Mesure, Allergie, DossierMedical)


def peut_etre_ferme(user):
    """Un compte du personnel ne se ferme pas depuis l'espace patient : il garderait un site sans administrateur."""
    return not (user.is_staff or user.is_superuser or getattr(user, "role", None) == user.Role.ADMIN)


def _horodatage(instant):
    return timezone.localtime(instant).isoformat(timespec="minutes") if instant else None


def construire_export(*, user, patient, dossier, allergies, mesures, consultations, demandes, maintenant):
    """Toutes les données d'un patient dans un dictionnaire prêt pour le JSON (jamais le mot de passe)."""
    return {
        "exporte_le": _horodatage(maintenant),
        "compte": {
            "identifiant": user.get_username(), "prenom": user.first_name, "nom": user.last_name,
            "email": user.email, "inscrit_le": _horodatage(patient.cree_le), "compte_actif": user.is_active,
        },
        "profil": {
            "date_naissance": patient.date_naissance.isoformat(), "sexe": patient.get_sexe_display(),
            "telephone": patient.telephone, "adresse": patient.adresse, "ville": patient.ville,
            "contact_urgence": {"nom": patient.contact_urgence_nom, "telephone": patient.contact_urgence_tel},
        },
        "consentement_ia": {"accepte": patient.consentement_ia, "le": _horodatage(patient.consentement_ia_le)},
        "dossier_medical": {
            "groupe_sanguin": dossier.groupe_sanguin if dossier else "",
            "antecedents": dossier.antecedents if dossier else "",
            "traitements_en_cours": dossier.traitements_en_cours if dossier else "",
        },
        "allergies": [
            {
                "substance": a.substance, "type": a.get_type_display(), "gravite": a.get_gravite_display(),
                "reaction": a.reaction, "decouverte_le": a.decouverte_le.isoformat() if a.decouverte_le else None,
                "active": a.active,
            }
            for a in allergies
        ],
        "mesures": [
            {
                "type": m.get_type_display(), "valeur": m.valeur, "valeur2": m.valeur2, "unite": m.unite,
                "date": _horodatage(m.mesure_le), "note": m.note,
            }
            for m in mesures
        ],
        "consultations": [
            {
                "date": _horodatage(c.date), "medecin": c.medecin_nom, "specialite": c.medecin_specialite, "motif": c.motif,
                "compte_rendu": c.resume, "diagnostic": c.diagnostic, "prescription": c.prescription,
                "recommandations": c.recommandations,
            }
            for c in consultations
        ],
        "demandes_de_rendez_vous": [
            {
                "date": _horodatage(t.cree_le), "medecin": t.medecin_nom, "statut": t.get_statut_display(),
                "niveau_urgence": t.niveau_effectif, "symptomes": [s.nom for s in t.symptomes or []],
                "temperature": float(t.constantes.temperature) if t.constantes and t.constantes.temperature is not None else None,
                "texte_libre": t.texte_libre, "creneau": _horodatage(t.creneau),
            }
            for t in demandes
        ],
    }


def donnees_patient(patient, maintenant=None):
    """Lit tout ce que le site garde sur ce patient et le met en forme (voir construire_export)."""
    return construire_export(
        user=patient.user,
        patient=patient,
        dossier=DossierMedical.objects.filter(patient=patient).first(),
        allergies=sorted(Allergie.objects.filter(patient=patient), key=lambda a: a.substance.lower()),
        mesures=sorted(Mesure.objects.filter(patient=patient), key=lambda m: m.mesure_le),
        consultations=sorted(Consultation.objects.filter(patient=patient), key=lambda c: c.date),
        demandes=sorted(Triage.objects.filter(patient=patient), key=lambda t: t.cree_le),
        maintenant=maintenant or timezone.now(),
    )


def _patient_de(user):
    try:
        return user.patient
    except Patient.DoesNotExist:
        return None


def desactiver(user):
    """Bloque la connexion et annule les demandes en attente (elles ne doivent plus occuper la file ni un créneau).

    Les données sont conservées : un administrateur peut réactiver le compte. Renvoie le nombre de demandes annulées."""
    annulees = 0
    patient = _patient_de(user)
    if patient is not None:
        for demande in Triage.objects.filter(patient=patient, statut=Triage.Statut.EN_ATTENTE):
            demande.statut = Triage.Statut.ANNULE
            demande.save(update_fields=["statut"])
            annulees += 1
    user.is_active = False
    user.save(update_fields=["is_active"])
    return annulees


def reactiver(user):
    user.is_active = True
    user.save(update_fields=["is_active"])


def supprimer(user):
    """Supprime définitivement le compte et tout ce qui s'y rattache. Irréversible."""
    patient = _patient_de(user)
    if patient is not None:
        for modele in MODELES_DU_PATIENT:
            for objet in modele.objects.filter(patient=patient):
                objet.delete()
        patient.delete()
    user.delete()
