import datetime
from decimal import Decimal
from unittest import mock

from bson import ObjectId
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from core.models import User
from patients.models import ConstantesVitales, Patient

from .models import Infirmier, InterventionDomicile, TypeSoin


def un_infirmier(valide=True, **champs):
    """Infirmier en mémoire (jamais enregistré) avec un identifiant, comme s'il venait de la base."""
    user = User(pk=ObjectId(), username="sami", first_name="Sami", last_name="Ben Ali", role="infirmier", est_valide=valide)
    valeurs = {"telephone": "21000000", "numero_ordre": "TN-1", "ville": "Tunis", "zones": ["Ariana"], **champs}
    return Infirmier(pk=ObjectId(), user=user, **valeurs)


def une_intervention(**champs):
    patient = Patient(pk=ObjectId(), user=User(username="amel", first_name="Amel", last_name="Test"))
    valeurs = {
        "type_soin": TypeSoin.INJECTION,
        "adresse": "1 rue de la Liberté",
        "ville": "Tunis",
        "date_souhaitee": timezone.localdate() + datetime.timedelta(days=1),
        **champs,
    }
    return InterventionDomicile(patient=patient, **valeurs)


def plus_tard(jours=1):
    return timezone.now() + datetime.timedelta(days=jours)


class SansBaseMixin:
    """full_clean() vérifierait l'existence du patient et de l'infirmier en base : on garde seulement clean()."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(InterventionDomicile, "full_clean", autospec=True, side_effect=lambda obj: obj.clean())
        p.start()
        self.addCleanup(p.stop)


class InfirmierModeleTests(SimpleTestCase):
    def test_relations(self):
        self.assertTrue(Infirmier._meta.get_field("user").one_to_one)
        self.assertEqual(Infirmier._meta.get_field("user").remote_field.related_name, "infirmier")
        self.assertTrue(Infirmier._meta.get_field("interventions").one_to_many)

    def test_valeurs_par_defaut(self):
        i = Infirmier()
        self.assertEqual((i.zones, i.soins, i.disponible), ([], [], True))

    def test_texte(self):
        self.assertEqual(str(un_infirmier()), "Sami Ben Ali")

    def test_villes_desservies_sans_doublon_ni_espaces(self):
        i = un_infirmier(ville=" Tunis ", zones=["ariana", "TUNIS", " Ariana ", "", "La  Marsa"])
        self.assertEqual(i.villes_desservies, ["Tunis", "ariana", "La Marsa"])

    def test_dessert_ignore_majuscules_et_espaces(self):
        i = un_infirmier()
        for ville in ("tunis", " TUNIS ", "Ariana"):
            with self.subTest(ville=ville):
                self.assertTrue(i.dessert(ville))
        self.assertFalse(i.dessert("Sfax"))

    def test_pratique_tous_les_soins_si_liste_vide(self):
        self.assertTrue(un_infirmier(soins=[]).pratique(TypeSoin.PERFUSION))
        limite = un_infirmier(soins=[TypeSoin.PANSEMENT])
        self.assertTrue(limite.pratique(TypeSoin.PANSEMENT))
        self.assertFalse(limite.pratique(TypeSoin.PERFUSION))

    def test_est_valide_suit_le_compte(self):
        self.assertTrue(un_infirmier(valide=True).est_valide)
        self.assertFalse(un_infirmier(valide=False).est_valide)
        inactif = un_infirmier()
        inactif.user.is_active = False
        self.assertFalse(inactif.est_valide)

    def test_clean_normalise_numero_et_zones(self):
        i = un_infirmier(numero_ordre=" tn-42 ", ville=" Tunis ", zones=["tunis", "Ariana"])
        i.clean()
        self.assertEqual((i.numero_ordre, i.ville, i.zones), ("TN-42", "Tunis", ["Ariana"]))

    def test_clean_refuse_un_compte_qui_n_est_pas_infirmier(self):
        i = un_infirmier()
        i.user.role = "patient"
        with self.assertRaises(ValidationError) as ctx:
            i.clean()
        self.assertIn("user", ctx.exception.message_dict)

    def test_soin_hors_liste_refuse(self):
        with self.assertRaises(ValidationError) as ctx:
            un_infirmier(soins=["massage"]).clean_fields(exclude=["user"])
        self.assertIn("soins", ctx.exception.message_dict)


class InterventionModeleTests(SimpleTestCase):
    def test_relations(self):
        self.assertIs(InterventionDomicile._meta.get_field("patient").related_model, Patient)
        self.assertEqual(InterventionDomicile._meta.get_field("patient").remote_field.related_name, "interventions")
        self.assertTrue(InterventionDomicile._meta.get_field("infirmier").null)
        self.assertTrue(InterventionDomicile._meta.get_field("consultation").null)

    def test_valeurs_par_defaut(self):
        i = InterventionDomicile()
        self.assertEqual((i.statut, i.moment, i.infirmier_id), ("demandee", "indifferent", None))
        self.assertTrue(i.est_modifiable)

    def test_texte(self):
        self.assertEqual(str(une_intervention()), "Injection – Amel Test (demandée)")

    def test_demande_valide(self):
        une_intervention().clean()

    def test_date_souhaitee_passee_refusee_pour_une_demande(self):
        hier = timezone.localdate() - datetime.timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            une_intervention(date_souhaitee=hier).clean()
        self.assertIn("date_souhaitee", ctx.exception.message_dict)

    def test_date_passee_acceptee_une_fois_realisee(self):
        hier = timezone.localdate() - datetime.timedelta(days=1)
        une_intervention(
            date_souhaitee=hier, statut="realisee", infirmier=un_infirmier(), date_prevue=timezone.now(),
            compte_rendu="Fait.", realisee_le=timezone.now(),
        ).clean()

    def test_acceptee_sans_infirmier_ni_heure_refusee(self):
        with self.assertRaises(ValidationError) as ctx:
            une_intervention(statut="acceptee").clean()
        self.assertEqual(set(ctx.exception.message_dict), {"infirmier", "date_prevue"})

    def test_realisee_sans_compte_rendu_refusee(self):
        with self.assertRaises(ValidationError) as ctx:
            une_intervention(statut="realisee", infirmier=un_infirmier(), date_prevue=timezone.now(), compte_rendu="  ").clean()
        self.assertIn("compte_rendu", ctx.exception.message_dict)

    def test_annulee_sans_motif_refusee(self):
        with self.assertRaises(ValidationError) as ctx:
            une_intervention(statut="annulee").clean()
        self.assertIn("motif_annulation", ctx.exception.message_dict)

    def test_choix_hors_liste_refuses(self):
        for champ, valeur in (("type_soin", "massage"), ("statut", "perdue"), ("moment", "nuit")):
            with self.subTest(champ=champ):
                with self.assertRaises(ValidationError) as ctx:
                    une_intervention(**{champ: valeur}).clean_fields(exclude=["patient", "infirmier", "consultation"])
                self.assertIn(champ, ctx.exception.message_dict)


class AccepterTests(SansBaseMixin, SimpleTestCase):
    def test_acceptation(self):
        it, inf, passage = une_intervention(), un_infirmier(), plus_tard()
        it.accepter(inf, passage)
        self.assertEqual((it.statut, it.infirmier, it.date_prevue), ("acceptee", inf, passage))
        self.assertIsNotNone(it.acceptee_le)

    def test_ville_en_minuscules_acceptee(self):
        it = une_intervention(ville="ariana")
        it.accepter(un_infirmier(), plus_tard())
        self.assertEqual(it.statut, "acceptee")

    def test_refus(self):
        cas = {
            "compte non validé": (une_intervention(), un_infirmier(valide=False), plus_tard()),
            "indisponible": (une_intervention(), un_infirmier(disponible=False), plus_tard()),
            "hors zone": (une_intervention(ville="Sfax"), un_infirmier(), plus_tard()),
            "soin non pratiqué": (une_intervention(type_soin=TypeSoin.PERFUSION), un_infirmier(soins=[TypeSoin.INJECTION]), plus_tard()),
            "heure passée": (une_intervention(), un_infirmier(), plus_tard(-1)),
            "déjà acceptée": (une_intervention(statut="acceptee"), un_infirmier(), plus_tard()),
        }
        for nom, (it, inf, passage) in cas.items():
            with self.subTest(nom):
                statut = it.statut
                with self.assertRaises(ValidationError):
                    it.accepter(inf, passage)
                self.assertEqual(it.statut, statut)

    def test_echec_de_validation_restaure_l_etat(self):
        it = une_intervention()
        with mock.patch.object(InterventionDomicile, "clean", side_effect=ValidationError("non")):
            with self.assertRaises(ValidationError):
                it.accepter(un_infirmier(), plus_tard())
        self.assertEqual((it.statut, it.infirmier_id, it.date_prevue, it.acceptee_le), ("demandee", None, None, None))


class TerminerEtAnnulerTests(SansBaseMixin, SimpleTestCase):
    def acceptee(self):
        it = une_intervention()
        it.accepter(un_infirmier(), plus_tard())
        return it

    def test_terminer_avec_constantes(self):
        it = self.acceptee()
        it.terminer("  Injection faite.  ", ConstantesVitales(temperature=Decimal("37.5")))
        self.assertEqual((it.statut, it.compte_rendu), ("realisee", "Injection faite."))
        self.assertEqual(it.constantes.temperature, Decimal("37.5"))
        self.assertIsNotNone(it.realisee_le)
        self.assertFalse(it.est_modifiable)

    def test_terminer_sans_compte_rendu_refuse_et_restaure(self):
        it = self.acceptee()
        with self.assertRaises(ValidationError):
            it.terminer("")
        self.assertEqual((it.statut, it.realisee_le), ("acceptee", None))

    def test_terminer_dans_le_futur_refuse(self):
        it = self.acceptee()
        with self.assertRaises(ValidationError):
            it.terminer("Fait.", realisee_le=plus_tard())

    def test_terminer_une_demande_refuse(self):
        with self.assertRaises(ValidationError):
            une_intervention().terminer("Fait.")

    def test_annuler_une_demande_ou_une_acceptee(self):
        for it in (une_intervention(), self.acceptee()):
            with self.subTest(statut=it.statut):
                it.annuler(" Patient hospitalisé ")
                self.assertEqual((it.statut, it.motif_annulation), ("annulee", "Patient hospitalisé"))
                self.assertIsNotNone(it.annulee_le)

    def test_annuler_sans_motif_refuse_et_restaure(self):
        it = une_intervention()
        with self.assertRaises(ValidationError):
            it.annuler("   ")
        self.assertEqual((it.statut, it.annulee_le), ("demandee", None))

    def test_une_intervention_close_ne_s_annule_plus(self):
        it = self.acceptee()
        it.terminer("Fait.")
        with self.assertRaises(ValidationError):
            it.annuler("Trop tard")


class AdminTests(SimpleTestCase):
    def test_modeles_enregistres(self):
        self.assertIn(Infirmier, admin.site._registry)
        self.assertIn(InterventionDomicile, admin.site._registry)

    def test_controles_de_l_admin(self):
        for modele in (Infirmier, InterventionDomicile):
            with self.subTest(modele=modele.__name__):
                self.assertEqual(admin.site._registry[modele].check(), [])
