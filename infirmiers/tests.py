import datetime
from decimal import Decimal
from unittest import mock

from bson import ObjectId
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from core.models import User
from core.views import ConnexionView
from patients.models import ConstantesVitales, Patient

from . import views
from .forms import AnnulationForm, CompteRenduForm, InscriptionInfirmierForm, PassageForm, ProfilInfirmierForm
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

    def test_date_passee_toleree_pour_une_demande_deja_enregistree(self):
        it = une_intervention(date_souhaitee=timezone.localdate() - datetime.timedelta(days=3))
        it._state.adding = False  # comme une demande relue depuis la base
        it.clean()

    def test_a_cloturer(self):
        self.assertTrue(une_intervention(statut="acceptee", date_prevue=plus_tard(-1)).a_cloturer)
        self.assertFalse(une_intervention(statut="acceptee", date_prevue=plus_tard()).a_cloturer)
        self.assertFalse(une_intervention(statut="realisee", date_prevue=plus_tard(-1)).a_cloturer)

    def test_heure_conseillee_selon_le_moment(self):
        self.assertEqual(une_intervention(moment="matin").heure_conseillee, (9, 0))
        self.assertEqual(une_intervention(moment="apres_midi").heure_conseillee, (14, 0))
        self.assertEqual(une_intervention().heure_conseillee, (10, 0))

    def test_demandes_pour_un_infirmier_sans_ville(self):
        demandes = InterventionDomicile.objects.demandes_pour(un_infirmier(ville="", zones=[]))
        self.assertTrue(demandes.query.is_empty())  # aucune requête : la liste est vide d'office

    def test_date_passee_acceptee_une_fois_realisee(self):
        hier = timezone.localdate() - datetime.timedelta(days=1)
        it = une_intervention(
            date_souhaitee=hier, statut="realisee", infirmier=un_infirmier(), date_prevue=timezone.now(),
            compte_rendu="Fait.", realisee_le=timezone.now(),
        )
        it._state.adding = False
        it.clean()

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

    def test_replanifier(self):
        it = self.acceptee()
        nouveau = plus_tard(3)
        it.replanifier(nouveau)
        self.assertEqual(it.date_prevue, nouveau)
        with self.assertRaises(ValidationError):
            it.replanifier(plus_tard(-1))
        self.assertEqual(it.date_prevue, nouveau)
        with self.assertRaises(ValidationError):
            une_intervention().replanifier(plus_tard())

    def test_liberer_rend_la_demande(self):
        it = self.acceptee()
        it.liberer()
        self.assertEqual((it.statut, it.infirmier_id, it.date_prevue, it.acceptee_le), ("demandee", None, None, None))
        with self.assertRaises(ValidationError):
            it.liberer()


# --- Formulaires ---------------------------------------------------------------------------


def donnees_inscription(**kw):
    valeurs = {
        "username": "rania", "first_name": "Rania", "last_name": "Essai", "email": "rania@exemple.tn",
        "password1": "Tres-Secret-2026", "password2": "Tres-Secret-2026",
        "telephone": "24000000", "numero_ordre": " tn-55 ", "ville": "Tunis", "zones": "Ariana, , la  Marsa",
        "soins": ["pansement"],
    }
    valeurs.update(kw)
    return valeurs


class InscriptionFormTests(SimpleTestCase):
    def setUp(self):
        # Aucun accès à la base : unicité de l'identifiant, de l'e-mail et du numéro d'Ordre remplacée.
        for cible in ("infirmiers.forms.email_deja_utilise", "infirmiers.forms.numero_ordre_utilise"):
            p = mock.patch(cible, return_value=False)
            p.start()
            self.addCleanup(p.stop)
        for nom, remplacement in (("clean_username", lambda form: form.cleaned_data["username"]), ("validate_unique", lambda form: None)):
            p = mock.patch.object(InscriptionInfirmierForm, nom, remplacement)
            p.start()
            self.addCleanup(p.stop)

    def test_donnees_nettoyees(self):
        form = InscriptionInfirmierForm(donnees_inscription())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["numero_ordre"], "TN-55")
        self.assertEqual(form.cleaned_data["zones"], ["Ariana", "la Marsa"])
        self.assertEqual(form.cleaned_data["soins"], ["pansement"])

    def test_soins_et_zones_facultatifs(self):
        form = InscriptionInfirmierForm(donnees_inscription(zones="", soins=[]))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.cleaned_data["zones"], form.cleaned_data["soins"]), ([], []))

    def test_champs_obligatoires(self):
        form = InscriptionInfirmierForm(donnees_inscription(telephone="", numero_ordre="", ville=""))
        self.assertFalse(form.is_valid())
        self.assertTrue({"telephone", "numero_ordre", "ville"} <= set(form.errors))

    def test_numero_ordre_deja_pris(self):
        with mock.patch("infirmiers.forms.numero_ordre_utilise", return_value=True):
            form = InscriptionInfirmierForm(donnees_inscription())
            self.assertFalse(form.is_valid())
        self.assertIn("numero_ordre", form.errors)

    def test_soin_inconnu_refuse(self):
        form = InscriptionInfirmierForm(donnees_inscription(soins=["massage"]))
        self.assertFalse(form.is_valid())
        self.assertIn("soins", form.errors)


class ProfilFormTests(SimpleTestCase):
    def test_valeurs_initiales(self):
        form = ProfilInfirmierForm(instance=un_infirmier(zones=["Ariana", "La Marsa"]))
        self.assertEqual(form.initial["first_name"], "Sami")
        self.assertEqual(form.initial["zones"], "Ariana, La Marsa")


class PassageFormTests(SimpleTestCase):
    def test_heure_proposee_selon_le_moment_souhaite(self):
        jour = timezone.localdate() + datetime.timedelta(days=2)
        form = PassageForm(intervention=une_intervention(date_souhaitee=jour, moment="apres_midi"))
        self.assertEqual(form.initial["date_prevue"], datetime.datetime.combine(jour, datetime.time(14, 0)))

    def test_demande_en_retard_proposee_aujourd_hui(self):
        it = une_intervention(date_souhaitee=timezone.localdate() - datetime.timedelta(days=2))
        self.assertEqual(PassageForm(intervention=it).initial["date_prevue"].date(), timezone.localdate())

    def test_date_passee_refusee(self):
        hier = timezone.localtime() - datetime.timedelta(days=1)
        form = PassageForm({"date_prevue": hier.strftime("%Y-%m-%dT%H:%M")})
        self.assertFalse(form.is_valid())
        self.assertIn("date_prevue", form.errors)


class CompteRenduFormTests(SimpleTestCase):
    def donnees(self, **kw):
        valeurs = {"compte_rendu": "Fait.", "realisee_le": timezone.localtime().strftime("%Y-%m-%dT%H:%M")}
        valeurs.update(kw)
        return valeurs

    def test_sans_constantes(self):
        form = CompteRenduForm(self.donnees())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.constantes())

    def test_avec_constantes(self):
        form = CompteRenduForm(self.donnees(temperature="38.2", tension_systolique="130", tension_diastolique="80"))
        self.assertTrue(form.is_valid(), form.errors)
        c = form.constantes()
        self.assertEqual((c.temperature, c.tension_systolique, c.tension_diastolique), (Decimal("38.2"), 130, 80))

    def test_refus(self):
        cas = {
            "compte rendu vide": ({"compte_rendu": ""}, "compte_rendu"),
            "date future": ({"realisee_le": (timezone.localtime() + datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")}, "realisee_le"),
            "tension incomplète": ({"tension_systolique": "130"}, "tension_diastolique"),
            "tension inversée": ({"tension_systolique": "80", "tension_diastolique": "130"}, "tension_diastolique"),
            "température absurde": ({"temperature": "60"}, "temperature"),
            "saturation > 100": ({"saturation_oxygene": "120"}, "saturation_oxygene"),
        }
        for nom, (champs, attendu) in cas.items():
            with self.subTest(nom):
                form = CompteRenduForm(self.donnees(**champs))
                self.assertFalse(form.is_valid())
                self.assertIn(attendu, form.errors)


class AnnulationFormTests(SimpleTestCase):
    def test_motif_obligatoire(self):
        self.assertFalse(AnnulationForm({"motif": ""}).is_valid())
        self.assertTrue(AnnulationForm({"motif": "Patient absent"}).is_valid())


# --- Adresses et droits d'accès ----------------------------------------------------------------


class UrlsTests(SimpleTestCase):
    def test_adresses(self):
        pk = str(ObjectId())
        cas = {
            "/infirmiers/inscription/": "inscription",
            "/infirmiers/tableau-de-bord/": "tableau_de_bord",
            "/infirmiers/demandes/": "demandes",
            "/infirmiers/planning/": "planning",
            "/infirmiers/historique/": "historique",
            "/infirmiers/profil/": "profil",
            f"/infirmiers/interventions/{pk}/": "intervention",
            f"/infirmiers/interventions/{pk}/accepter/": "accepter",
            f"/infirmiers/interventions/{pk}/replanifier/": "replanifier",
            f"/infirmiers/interventions/{pk}/compte-rendu/": "terminer",
            f"/infirmiers/interventions/{pk}/annuler/": "annuler",
            f"/infirmiers/interventions/{pk}/liberer/": "liberer",
        }
        for url, nom in cas.items():
            with self.subTest(url=url):
                self.assertEqual(resolve(url).view_name, f"infirmiers:{nom}")


class DroitsTests(SimpleTestCase):
    VUES = ("tableau_de_bord", "demandes", "planning", "historique", "profil")
    VUES_INTERVENTION = ("intervention", "replanifier", "terminer", "annuler")

    def appeler(self, nom, user, *args):
        requete = RequestFactory().get("/infirmiers/")
        requete.user = user
        return getattr(views, nom)(requete, *args)

    def test_anonyme_renvoye_vers_la_connexion(self):
        for nom in self.VUES + self.VUES_INTERVENTION:
            args = ("x",) if nom in self.VUES_INTERVENTION else ()
            with self.subTest(vue=nom):
                reponse = self.appeler(nom, AnonymousUser(), *args)
                self.assertEqual(reponse.status_code, 302)
                self.assertTrue(reponse["Location"].startswith(reverse("core:connexion")))

    def test_un_compte_sans_profil_infirmier_est_refuse(self):
        patient = User(username="amel", role="patient")  # jamais enregistré : aucun profil infirmier
        for nom in self.VUES + self.VUES_INTERVENTION:
            args = ("x",) if nom in self.VUES_INTERVENTION else ()
            with self.subTest(vue=nom):
                with self.assertRaises(PermissionDenied):
                    self.appeler(nom, patient, *args)

    def test_les_actions_n_acceptent_que_post(self):
        for nom in ("accepter", "liberer"):
            requete = RequestFactory().get("/")
            requete.user = User(username="sami", role="infirmier")
            with self.subTest(vue=nom):
                self.assertEqual(getattr(views, nom)(requete, "x").status_code, 405)

    def test_connexion_d_un_infirmier_mene_a_son_tableau_de_bord(self):
        vue = ConnexionView()
        vue.request = RequestFactory().get("/comptes/connexion/")
        vue.request.user = User(username="sami", role="infirmier")
        self.assertEqual(vue.get_default_redirect_url(), reverse("infirmiers:tableau_de_bord"))


class AdminTests(SimpleTestCase):
    def test_modeles_enregistres(self):
        self.assertIn(Infirmier, admin.site._registry)
        self.assertIn(InterventionDomicile, admin.site._registry)

    def test_controles_de_l_admin(self):
        for modele in (Infirmier, InterventionDomicile):
            with self.subTest(modele=modele.__name__):
                self.assertEqual(admin.site._registry[modele].check(), [])
