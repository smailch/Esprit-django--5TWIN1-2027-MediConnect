import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from patients import medecins_test
from patients.models import (
    Allergie,
    AutoEvaluation,
    ConstantesVitales,
    DossierMedical,
    Patient,
    Symptome,
    SymptomeDeclare,
    Triage,
)
from patients.triage import evaluer

PREFIXE = "demo_"

# (identifiant, prénom, nom, ville, sexe, né le, téléphone)
PATIENTS = [
    ("amel", "Amel", "Trabelsi", "Tunis", "F", datetime.date(1988, 4, 12), "20111222"),
    ("karim", "Karim", "Jaziri", "Sfax", "H", datetime.date(1975, 9, 3), "20333444"),
    ("sonia", "Sonia", "Mejri", "Sousse", "F", datetime.date(1996, 1, 25), "20555666"),
    ("hichem", "Hichem", "Ben Ali", "Tunis", "H", datetime.date(1963, 11, 8), "20777888"),
    ("nour", "Nour", "Chaabane", "Sfax", "F", datetime.date(2001, 6, 30), "20999000"),
    ("rami", "Rami", "Gharbi", "Tunis", "H", datetime.date(1990, 2, 17), "20121314"),
]

# (patient, substance, type, gravité, réaction)
ALLERGIES = [
    ("sonia", "Pénicilline", "medicament", "severe", "Gonflement du visage, gêne respiratoire"),
    ("hichem", "Aspirine", "medicament", "moderee", "Éruption cutanée"),
    ("karim", "Pollen de graminées", "environnement", "legere", "Éternuements, yeux qui piquent"),
    ("amel", "Arachide", "aliment", "severe", "Urticaire, malaise"),
    ("amel", "Œufs", "aliment", "legere", "Maux de ventre"),
]

# (patient, médecin, symptômes, auto-évaluation, température, texte, statut, il y a (heures), niveau médecin)
DEMANDES = [
    ("hichem", "m1", ["Douleur thoracique"], {"douleur": 4, "respiration": 4, "etat_general": 4}, None,
     "Douleur qui serre la poitrine depuis une heure.", "en_attente", 0.4, None),
    ("karim", "m1", ["Maux de tête", "Vertiges"], {"douleur": 3, "etat_general": 3}, None, "", "en_attente", 2, None),
    ("sonia", "m1", ["Toux", "Fatigue"], {"fievre": 2, "etat_general": 2}, 38.2,
     "Toux sèche depuis trois jours.", "en_attente", 5, None),
    ("amel", "m2", ["Difficulté à respirer"], {"respiration": 5, "etat_general": 4}, None, "", "en_consultation", 1.5, None),
    ("nour", "m2", ["Fatigue"], {"etat_general": 1}, None, "Fatigue passagère.", "en_attente", 8, None),
    ("rami", "m4", ["Vomissements", "Douleur abdominale"], {"douleur": 3, "fievre": 3}, None, "", "en_attente", 26, 3),
    ("amel", "m4", ["Mal de gorge"], {"fievre": 1}, None, "", "termine", 72, None),
    ("karim", "m5", ["Toux"], {"respiration": 2}, None, "", "termine", 96, None),
    ("sonia", "m6", ["Éruption cutanée"], {}, None, "Plaques rouges sur les bras.", "annule", 50, None),
    ("nour", "m3", ["Maux de tête"], {"douleur": 2}, None, "", "termine", 120, None),
]


class Command(BaseCommand):
    help = "Charge des patients et des demandes fictifs pour la démonstration (--supprimer pour les retirer)."

    def add_arguments(self, parser):
        parser.add_argument("--supprimer", action="store_true", help="Supprime les données de démonstration.")

    def handle(self, *args, **options):
        User = get_user_model()
        if options["supprimer"]:
            return self.supprimer(User)

        if User.objects.filter(username__startswith=PREFIXE).exists():
            ajoutees = self.ajouter_allergies(User)
            self.stdout.write(
                "Les données de démonstration sont déjà chargées (utilisez --supprimer pour les retirer)."
                + (f" {ajoutees} allergie(s) de démonstration ajoutée(s)." if ajoutees else "")
            )
            return
        if not Symptome.objects.exists():
            self.stdout.write(self.style.ERROR("Le catalogue est vide : lancez d'abord charger_symptomes."))
            return

        patients = {}
        for identifiant, prenom, nom, ville, sexe, naissance, telephone in PATIENTS:
            user = User(
                username=PREFIXE + identifiant, first_name=prenom, last_name=nom,
                email=f"{identifiant}@demo.mediconnect.test", role=User.Role.PATIENT,
            )
            user.set_unusable_password()  # compte de démonstration : aucune connexion possible
            user.save()
            patient = Patient.objects.create(
                user=user, date_naissance=naissance, sexe=sexe, telephone=telephone, ville=ville
            )
            DossierMedical.objects.create(patient=patient)
            patients[identifiant] = patient

        catalogue = {s.nom: s for s in Symptome.objects.all()}
        maintenant = timezone.now()
        for ident, med_id, noms, auto, temp, texte, statut, heures, niveau_medecin in DEMANDES:
            medecin = medecins_test.trouver(med_id)
            symptomes = [
                {"nom": s.nom, "poids": s.poids, "drapeau_rouge": s.drapeau_rouge, "niveau_minimal": s.niveau_minimal}
                for s in (catalogue[n] for n in noms if n in catalogue)
            ]
            constantes = {"temperature": temp} if temp else {}
            auto_complete = {k: auto.get(k, 0) for k in ("douleur", "fievre", "respiration", "etat_general")}
            resultat = evaluer(symptomes, constantes, auto_complete)
            triage = Triage.objects.create(
                patient=patients[ident], medecin_id=medecin["id"], medecin_nom=medecin["nom"],
                medecin_specialite=medecin["specialite"], statut=statut,
                symptomes=[
                    SymptomeDeclare(nom=d["nom"], poids=d["poids"], drapeau_rouge=d["drapeau_rouge"])
                    for d in symptomes
                ],
                constantes=ConstantesVitales(**constantes) if constantes else None,
                auto_evaluation=AutoEvaluation(**auto_complete),
                texte_libre=texte, score=resultat.score, niveau=resultat.niveau,
                explication=resultat.explication, drapeaux_rouges=resultat.drapeaux_rouges,
                niveau_medecin=niveau_medecin,
            )
            # La date d'arrivée est posée automatiquement : on la recule pour varier les exemples.
            Triage.objects.filter(pk=triage.pk).update(cree_le=maintenant - datetime.timedelta(hours=heures))

        ajoutees = self.ajouter_allergies(User)
        self.stdout.write(self.style.SUCCESS(
            f"{len(PATIENTS)} patients, {len(DEMANDES)} demandes et {ajoutees} allergies de démonstration créés."))

    def ajouter_allergies(self, User):
        """Allergies de démonstration (sans doublon si la commande est relancée)."""
        ajoutees = 0
        for ident, substance, type_, gravite, reaction in ALLERGIES:
            patient = Patient.objects.filter(user__username=PREFIXE + ident).first()
            if patient is None or Allergie.objects.filter(patient=patient, substance__iexact=substance).exists():
                continue
            Allergie.objects.create(patient=patient, substance=substance, type=type_, gravite=gravite, reaction=reaction)
            ajoutees += 1
        return ajoutees

    def supprimer(self, User):
        # MongoDB ne supprime pas à travers plusieurs collections : objet par objet.
        comptes = 0
        for user in User.objects.filter(username__startswith=PREFIXE):
            for patient in Patient.objects.filter(user=user):
                for triage in Triage.objects.filter(patient=patient):
                    triage.delete()
                for allergie in Allergie.objects.filter(patient=patient):
                    allergie.delete()
                for dossier in DossierMedical.objects.filter(patient=patient):
                    dossier.delete()
                patient.delete()
            user.delete()
            comptes += 1
        self.stdout.write(self.style.SUCCESS(f"{comptes} compte(s) de démonstration supprimé(s)."))
