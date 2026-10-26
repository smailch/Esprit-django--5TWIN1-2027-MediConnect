"""Tests d'intégration de l'espace patient : vraie base (MongoDB de test) et client HTTP de Django.

Inscription (création du compte et du profil), puis CRUD complet des allergies et des mesures par les pages.
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from core import fabriques_test as f
from core.models import User

from .models import Allergie, Mesure, Patient


def inscription(**kw):
    donnees = {
        "username": "amel", "first_name": "Amel", "last_name": "Ben Salah", "email": "amel@exemple.tn",
        "password1": f.MOT_DE_PASSE, "password2": f.MOT_DE_PASSE, "date_naissance": "1990-04-12", "sexe": "F",
        "telephone": "20 123 456", "ville": "Tunis",
    }
    donnees.update(kw)
    return donnees


class InscriptionPatientTests(TestCase):
    def test_inscription_puis_espace_patient(self):
        reponse = self.client.post("/patients/inscription/", inscription())
        self.assertRedirects(reponse, "/patients/tableau-de-bord/")
        patient = Patient.objects.select_related("user").get(user__username="amel")
        self.assertEqual((patient.user.role, patient.ville), (User.Role.PATIENT, "Tunis"))
        self.assertEqual(self.client.get("/patients/dossier/").status_code, 200)

    def test_email_deja_utilise_refuse(self):
        f.un_patient("lina")
        reponse = self.client.post("/patients/inscription/", inscription(username="autre", email="lina@exemple.tn"))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("email", reponse.context["form"].errors)
        self.assertFalse(User.objects.filter(username="autre").exists())


class AllergiesCrudTests(TestCase):
    def setUp(self):
        self.patient = f.un_patient("amel")
        self.client.force_login(self.patient.user)

    def test_creer_lire_modifier_supprimer(self):
        reponse = self.client.post("/patients/allergies/nouvelle/", {
            "substance": "Pénicilline", "type": "medicament", "gravite": "severe", "reaction": "Œdème", "active": "on",
        })
        self.assertRedirects(reponse, "/patients/allergies/")
        allergie = Allergie.objects.get()
        self.assertEqual((allergie.patient, allergie.substance, allergie.gravite), (self.patient, "Pénicilline", "severe"))
        self.assertContains(self.client.get("/patients/allergies/"), "Pénicilline")

        self.client.post(f"/patients/allergies/{allergie.pk}/modifier/", {
            "substance": "Pénicilline", "type": "medicament", "gravite": "moderee", "reaction": "Urticaire", "active": "on",
        })
        allergie.refresh_from_db()
        self.assertEqual((allergie.gravite, allergie.reaction), ("moderee", "Urticaire"))

        self.assertEqual(self.client.get(f"/patients/allergies/{allergie.pk}/supprimer/").status_code, 200)
        self.assertRedirects(self.client.post(f"/patients/allergies/{allergie.pk}/supprimer/"), "/patients/allergies/")
        self.assertFalse(Allergie.objects.exists())

    def test_substance_obligatoire(self):
        reponse = self.client.post("/patients/allergies/nouvelle/", {"substance": "", "type": "medicament", "gravite": "severe"})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("substance", reponse.context["form"].errors)


class MesuresCrudTests(TestCase):
    def setUp(self):
        self.patient = f.un_patient("amel")
        self.client.force_login(self.patient.user)
        self.quand = (timezone.localtime() - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    def test_creer_modifier_supprimer_et_exporter(self):
        reponse = self.client.post("/patients/mesures/nouvelle/", {"type": "poids", "valeur": "68.5", "mesure_le": self.quand})
        self.assertRedirects(reponse, "/patients/mesures/")
        mesure = Mesure.objects.get()
        self.client.post(f"/patients/mesures/{mesure.pk}/modifier/", {"type": "poids", "valeur": "67", "mesure_le": self.quand})
        mesure.refresh_from_db()
        self.assertEqual(mesure.valeur, 67)
        export = self.client.get("/patients/mesures/export/")
        self.assertEqual(export["Content-Type"], "text/csv; charset=utf-8")
        self.client.post(f"/patients/mesures/{mesure.pk}/supprimer/")
        self.assertFalse(Mesure.objects.exists())

    def test_valeur_impossible_refusee(self):
        reponse = self.client.post("/patients/mesures/nouvelle/", {"type": "temperature", "valeur": "60", "mesure_le": self.quand})
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["form"].errors)
        self.assertFalse(Mesure.objects.exists())
