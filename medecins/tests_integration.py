"""Tests d'intégration de l'espace médecin : vraie base (MongoDB de test) et client HTTP de Django.

Inscription (compte en attente), validation par l'administrateur depuis la page « Comptes », puis profil.
"""
from django.test import Client, TestCase

from core import fabriques_test as f
from core.models import User

from .models import Medecin


class InscriptionEtValidationTests(TestCase):
    def test_inscription_validation_puis_acces(self):
        reponse = self.client.post("/medecins/inscription/", {
            "username": "dr_sara", "first_name": "Sara", "last_name": "Benali", "email": "sara@exemple.tn",
            "password1": f.MOT_DE_PASSE, "password2": f.MOT_DE_PASSE, "specialite": "Pédiatrie", "ville": "Sousse",
            "telephone": "73 111 222", "plage_0": "9-12, 14-17",
        })
        self.assertRedirects(reponse, "/medecins/en-attente/", fetch_redirect_response=False)
        medecin = Medecin.objects.select_related("user").get(user__username="dr_sara")
        self.assertEqual((medecin.user.role, medecin.user.est_valide, medecin.specialite), (User.Role.MEDECIN, False, "Pédiatrie"))
        self.assertTrue(medecin.plages)

        administrateur = Client()
        administrateur.force_login(f.un_admin())
        administrateur.post(f"/backoffice/comptes/{medecin.user.pk}/valider/")
        medecin.user.refresh_from_db()
        self.assertTrue(medecin.user.est_valide)
        self.assertEqual(self.client.get("/medecins/").status_code, 200)

    def test_profil_modifie(self):
        medecin = f.un_medecin("dr_ali")
        self.client.force_login(medecin.user)
        reponse = self.client.post("/medecins/profil/", {
            "first_name": "Ali", "last_name": "Test", "email": "ali@exemple.tn", "specialite": "Cardiologie", "ville": "Tunis",
            "telephone": "71 000 000", "numero_ordre": "", "disponible": "on", "presentation": "", "plage_1": "8-12",
        })
        self.assertEqual(reponse.status_code, 302)
        medecin.refresh_from_db()
        self.assertEqual(medecin.specialite, "Cardiologie")


class ParcoursConsultationTests(TestCase):
    """De la demande du patient au compte rendu du médecin, puis aux soins à domicile et à la pharmacie (modules reliés)."""

    def test_file_requalification_consultation_et_prescriptions(self):
        from django.utils import timezone

        from infirmiers.models import InterventionDomicile
        from patients.models import Consultation, Triage

        from .models import Prescription

        medecin = f.un_medecin("dr_sara")
        patient = f.un_patient("amel")
        triage = Triage.objects.create(patient=patient, statut=Triage.Statut.EN_ATTENTE, medecin_id=medecin.code,
                                       medecin_nom="Dr Sara", niveau=3, texte_libre="Toux et fièvre depuis 3 jours")
        self.client.force_login(medecin.user)
        self.assertContains(self.client.get("/medecins/"), "Amel")
        self.assertContains(self.client.get(f"/medecins/file/{triage.pk}/"), "Toux et fièvre")

        self.client.post(f"/medecins/file/{triage.pk}/niveau/", {"niveau": "2"})  # le médecin garde la décision finale
        triage.refresh_from_db()
        self.assertEqual(triage.niveau_medecin, 2)
        self.client.post(f"/medecins/file/{triage.pk}/commencer/")
        triage.refresh_from_db()
        self.assertEqual(triage.statut, Triage.Statut.EN_CONSULTATION)

        reponse = self.client.post(f"/medecins/file/{triage.pk}/compte-rendu/", {
            "date": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "motif": "Toux fébrile", "resume": "Bronchite aiguë.",
            "diagnostic": "Bronchite", "recommandations": "Repos", "ordonnance": "Amoxicilline 1 g, 2 fois par jour, 6 jours",
            "examens": "", "soins": "Injection d'anticoagulant chaque jour pendant 5 jours",
        })
        consultation = Consultation.objects.get(triage=triage)
        self.assertRedirects(reponse, f"/medecins/consultations/{consultation.pk}/")
        triage.refresh_from_db()
        self.assertEqual(triage.statut, Triage.Statut.TERMINE)
        self.assertEqual(set(Prescription.objects.filter(consultation=consultation).values_list("type", flat=True)),
                         {Prescription.Type.ORDONNANCE, Prescription.Type.SOIN})
        self.assertContains(self.client.get("/medecins/consultations/"), "Bronchite")

        self.client.post(f"/medecins/consultations/{consultation.pk}/modifier/", {
            "date": timezone.localtime(consultation.date).strftime("%Y-%m-%dT%H:%M"), "motif": "Toux fébrile",
            "resume": "Bronchite aiguë.", "diagnostic": "Bronchite aiguë", "recommandations": "Repos",
            "ordonnance": "Amoxicilline 1 g, 2 fois par jour, 6 jours", "examens": "", "soins": "Injection d'anticoagulant chaque jour pendant 5 jours",
        })
        consultation.refresh_from_db()
        self.assertEqual(consultation.diagnostic, "Bronchite aiguë")

        # le patient retrouve le soin prescrit et le demande en un clic (formulaire pré-rempli)
        self.client.force_login(patient.user)
        self.assertContains(self.client.get("/infirmiers/soins/"), "Soins prescrits")
        soin = Prescription.objects.get(consultation=consultation, type=Prescription.Type.SOIN)
        formulaire = self.client.get(f"/infirmiers/soins/nouveau/?prescription={soin.pk}").context["form"]
        self.assertEqual((formulaire.initial["type_soin"], formulaire.initial["repetition"]), ("injection", "1"))
        self.assertFalse(InterventionDomicile.objects.exists())

        # suppression du compte rendu par le médecin
        self.client.force_login(medecin.user)
        self.client.post(f"/medecins/consultations/{consultation.pk}/supprimer/")
        self.assertFalse(Consultation.objects.filter(pk=consultation.pk).exists())

    def test_un_medecin_ne_voit_pas_la_file_d_un_autre(self):
        from patients.models import Triage

        autre = f.un_medecin()
        triage = Triage.objects.create(patient=f.un_patient(), statut=Triage.Statut.EN_ATTENTE, medecin_id=autre.code,
                                       medecin_nom="Dr Autre", niveau=4)
        self.client.force_login(f.un_medecin().user)
        self.assertEqual(self.client.get(f"/medecins/file/{triage.pk}/").status_code, 404)
