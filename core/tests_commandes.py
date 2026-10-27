"""Commandes de gestion, exécutées sur la vraie base de test : données de démonstration de chaque module (création
puis suppression), rôles, journal et évaluation de l'IA."""
import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import JournalConnexion, User
from infirmiers.models import Infirmier, InterventionDomicile
from medecins.models import Medecin
from patients.models import Patient, Symptome
from pharmacies.models import Medicament, Pharmacie


def lancer(*args, **options):
    sortie = StringIO()
    call_command(*args, stdout=sortie, stderr=StringIO(), **options)
    return sortie.getvalue()


@override_settings(IA_FOURNISSEUR="aucun")
class DonneesDeDemonstrationTests(TestCase):
    def test_chargement_puis_suppression_de_tous_les_modules(self):
        lancer("charger_symptomes")
        self.assertGreater(Symptome.objects.count(), 10)
        lancer("charger_medecins")
        self.assertGreater(Medecin.objects.count(), 3)
        lancer("charger_demo")
        self.assertTrue(Patient.objects.filter(user__username__startswith="demo_").exists())
        lancer("charger_demo_pharmacies", mot_de_passe="Demo-Pharma-2026!")
        self.assertTrue(Pharmacie.objects.exists() and Medicament.objects.exists())
        sortie = lancer("charger_demo_infirmiers", mot_de_passe="Demo-Soins-2026!")
        self.assertIn("infirmiers", sortie)
        self.assertEqual(Infirmier.objects.count(), 3)
        self.assertGreater(InterventionDomicile.objects.count(), 10)
        self.assertTrue(User.objects.get(username="demo_inf_sami").check_password("Demo-Soins-2026!"))
        # relancer ne crée pas de doublon
        lancer("charger_demo_infirmiers", mot_de_passe="Demo-Soins-2026!")
        self.assertEqual(Infirmier.objects.count(), 3)

        lancer("charger_demo_infirmiers", supprimer=True)
        self.assertFalse(Infirmier.objects.exists() or InterventionDomicile.objects.exists())
        lancer("charger_demo_pharmacies", supprimer=True)
        self.assertFalse(Pharmacie.objects.filter(user__username__startswith="demorx_").exists())
        lancer("charger_demo", supprimer=True)
        self.assertFalse(Patient.objects.filter(user__username__startswith="demo_").exists())


class CommandesDeMaintenanceTests(TestCase):
    def test_synchroniser_les_roles(self):
        user = User.objects.create_user("lina", password="x", role=User.Role.PHARMACIE)
        user.groups.clear()
        sortie = lancer("synchroniser_roles")
        self.assertIn("Administrateurs", sortie)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Pharmacies"])

    def test_purger_le_journal(self):
        ancienne = JournalConnexion.objects.create(evenement="echec", identifiant="vieux")
        ancienne.quand = timezone.now() - datetime.timedelta(days=120)
        ancienne.save()
        JournalConnexion.objects.create(evenement="connexion", identifiant="recent")
        self.assertIn("1 entrée", lancer("purger_journal", jours=90))
        self.assertEqual(list(JournalConnexion.objects.values_list("identifiant", flat=True)), ["recent"])

    def test_evaluer_les_alertes_sans_ia(self):
        sortie = lancer("evaluer_alertes", sans_ia=True, ne_pas_ecrire=True)
        self.assertIn("Corpus : 60 notes", sortie)
        self.assertIn("Exactitude", sortie)
        self.assertIn("signaler", sortie)
