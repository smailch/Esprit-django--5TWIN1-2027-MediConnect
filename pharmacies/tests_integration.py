"""Tests d'intégration du module pharmacies : vraie base (MongoDB de test) et client HTTP de Django.

CRUD des pharmacies par l'administrateur et du stock de médicaments par la pharmacie, avec ses droits.
"""
from django.test import TestCase

from core import fabriques_test as f
from core.models import User

from .models import Medicament, Pharmacie


class PharmacieCrudParLAdministrateurTests(TestCase):
    def setUp(self):
        self.client.force_login(f.un_admin())

    def test_creer_modifier_supprimer(self):
        compte = User.objects.create_user("rx_lac", password=f.MOT_DE_PASSE, role=User.Role.PHARMACIE)
        reponse = self.client.post("/backoffice/pharmacies/nouvelle/", {
            "user": compte.pk, "nom": "Pharmacie du Lac", "adresse": "Rue du Lac Léman", "ville": "Tunis",
            "telephone": "71 222 333", "horaires": "8 h - 20 h",
        })
        pharmacie = Pharmacie.objects.get(nom="Pharmacie du Lac")
        self.assertRedirects(reponse, f"/backoffice/pharmacies/{pharmacie.pk}/")
        self.client.post(f"/backoffice/pharmacies/{pharmacie.pk}/modifier/", {
            "user": compte.pk, "nom": "Pharmacie du Lac", "adresse": "Rue du Lac Léman", "ville": "La Marsa",
            "telephone": "71 222 333", "de_garde": "on",
        })
        pharmacie.refresh_from_db()
        self.assertEqual((pharmacie.ville, pharmacie.de_garde), ("La Marsa", True))
        self.client.post(f"/backoffice/pharmacies/{pharmacie.pk}/supprimer/")
        self.assertFalse(Pharmacie.objects.filter(pk=pharmacie.pk).exists())


class StockCrudTests(TestCase):
    def setUp(self):
        self.pharmacie = f.une_pharmacie("rx_centre")
        self.client.force_login(self.pharmacie.user)

    def test_creer_modifier_supprimer_un_medicament(self):
        self.client.post("/pharmacies/stock/nouveau/", {
            "nom": "Doliprane", "principe_actif": "paracétamol", "dosage": "1 g", "forme": "comprime", "quantite": 40, "seuil_alerte": 5,
        })
        medicament = Medicament.objects.get()
        self.assertEqual((medicament.pharmacie, medicament.quantite), (self.pharmacie, 40))
        self.assertContains(self.client.get("/pharmacies/stock/"), "Doliprane")
        self.client.post(f"/pharmacies/stock/{medicament.pk}/modifier/", {
            "nom": "Doliprane", "principe_actif": "paracétamol", "dosage": "1 g", "forme": "comprime", "quantite": 0, "seuil_alerte": 5,
        })
        medicament.refresh_from_db()
        self.assertTrue(medicament.est_en_rupture)
        self.client.post(f"/pharmacies/stock/{medicament.pk}/supprimer/")
        self.assertFalse(Medicament.objects.exists())

    def test_le_stock_d_une_autre_pharmacie_est_inaccessible(self):
        autre = f.une_pharmacie("rx_autre")
        medicament = Medicament.objects.create(pharmacie=autre, nom="Augmentin", quantite=3, seuil_alerte=1)
        reponse = self.client.post(f"/pharmacies/stock/{medicament.pk}/supprimer/")
        self.assertIn(reponse.status_code, (403, 404))
        self.assertTrue(Medicament.objects.filter(pk=medicament.pk).exists())
