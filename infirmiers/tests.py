import datetime
from decimal import Decimal
from unittest import mock

from bson import ObjectId
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from core.models import User
from core.views import ConnexionView
from patients import ia_client
from patients.models import ConstantesVitales, Mesure, Patient

from . import alertes, dossier, ia_soin, notifications, views, views_patient
from .forms import AnnulationForm, CompteRenduForm, DemandeSoinForm, InscriptionInfirmierForm, PassageForm, ProfilInfirmierForm
from .models import Infirmier, InterventionDomicile, TypeSoin, passage_en_conflit, prochain_creneau_libre


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


# --- Compte rendu intelligent : règles ----------------------------------------------------------------


class ExtraireConstantesTests(SimpleTestCase):
    def valeurs(self, texte):
        return {nom: v for nom, (v, _) in alertes.extraire_constantes(texte).items()}

    def test_ecritures_courantes(self):
        cas = {
            "T 38,4, TA 150/90, pouls 98, sat 93 %": {
                "temperature": 38.4, "tension_systolique": 150, "tension_diastolique": 90, "frequence_cardiaque": 98, "saturation_oxygene": 93,
            },
            "Température : 37.2 °C ; tension artérielle 128/76 ; FC=72 ; SpO2 97%": {
                "temperature": 37.2, "tension_systolique": 128, "tension_diastolique": 76, "frequence_cardiaque": 72, "saturation_oxygene": 97,
            },
            "Fébrile à 38,9° ce matin, 110 bpm": {"temperature": 38.9, "frequence_cardiaque": 110},
        }
        for texte, attendu in cas.items():
            with self.subTest(texte):
                self.assertEqual(self.valeurs(texte), attendu)

    def test_tension_en_centimetres_de_mercure(self):
        self.assertEqual(self.valeurs("TA 15/9"), {"tension_systolique": 150, "tension_diastolique": 90})

    def test_valeurs_improbables_ignorees(self):
        self.assertEqual(self.valeurs("T 85, TA 90/150, sat 120 %"), {})

    def test_extrait_cite_le_texte(self):
        self.assertEqual(alertes.extraire_constantes("RAS. TA 15/9 au repos.")["tension_systolique"][1], "TA 15/9")

    def test_note_vide(self):
        self.assertEqual(alertes.extraire_constantes(""), {})


class SignesDuTexteTests(SimpleTestCase):
    def noms(self, texte):
        return {s.nom: s.extrait for s in alertes.signes_du_texte(texte)}

    def test_signes_reperes_avec_leur_extrait(self):
        noms = self.noms("Plaie un peu rouge et chaude. Patiente essoufflée, Œdème des chevilles, elle n'a pas pris son traitement.")
        self.assertEqual(noms, {
            "Signes d'infection de la plaie": "rouge et chaude",
            "Difficulté respiratoire": "essoufflée",
            "Œdème": "Œdème",
            "Traitement non pris": "n'a pas pris",
        })

    def test_signe_nie_ou_d_un_proche_ecarte(self):
        self.assertEqual(self.noms("Pas de rougeur, pas de fièvre. Son mari est tombé hier."), {})

    def test_point_de_piqure_enflamme(self):
        """Cas vu en test réel : l'IA ne l'a pas toujours repéré, les règles servent de filet."""
        self.assertEqual(self.noms("Le point de piqûre est un peu enflammé et chaud."), {"Signes d'infection de la plaie": "enflammé"})
        self.assertEqual(self.noms("Point de piqûre non enflammé."), {})

    def test_gravite_et_origine(self):
        signe = alertes.signes_du_texte("Saignement au point de ponction")[0]
        self.assertEqual((signe.gravite, signe.origine), ("signaler", "texte"))


class SeuilsEtEvolutionTests(SimpleTestCase):
    def test_seuils(self):
        cas = {
            "temperature": ((38.2, "surveiller"), (39.8, "signaler"), (35, "signaler"), (37, None)),
            "saturation_oxygene": ((93, "surveiller"), (88, "signaler"), (97, None)),
            "frequence_cardiaque": ((105, "surveiller"), (130, "signaler"), (70, None)),
        }
        for nom, valeurs in cas.items():
            for valeur, attendu in valeurs:
                with self.subTest(nom=nom, valeur=valeur):
                    signes = alertes.signes_des_constantes({nom: valeur})
                    self.assertEqual(signes[0].gravite if signes else None, attendu)

    def test_tension_un_seul_signe_le_plus_grave(self):
        signes = alertes.signes_des_constantes({"tension_systolique": 150, "tension_diastolique": 112})
        self.assertEqual([(s.nom, s.gravite, s.extrait) for s in signes], [("Tension très élevée", "signaler", "TA 150/112 mmHg")])

    def test_extrait_de_la_note_prefere(self):
        signe = alertes.signes_des_constantes({"temperature": 38.4}, {"temperature": "T 38,4"})[0]
        self.assertEqual(signe.extrait, "T 38,4")

    def test_degradation_sur_trois_releves(self):
        signes = alertes.signes_d_evolution([{"tension_systolique": 130}, {"tension_systolique": 142}], {"tension_systolique": 150})
        self.assertEqual(len(signes), 1)
        self.assertEqual(signes[0].origine, "evolution")
        self.assertIn("130 → 142 → 150", signes[0].extrait)

    def test_saturation_en_baisse(self):
        signes = alertes.signes_d_evolution([{"saturation_oxygene": 97}, {"saturation_oxygene": 95}], {"saturation_oxygene": 92})
        self.assertEqual([s.nom for s in signes], ["Saturation en baisse"])

    def test_pas_d_evolution_signalee(self):
        cas = {
            "trop peu de relevés": ([{"tension_systolique": 150}], {"tension_systolique": 160}),
            "pas toujours en hausse": ([{"tension_systolique": 150}, {"tension_systolique": 140}], {"tension_systolique": 155}),
            "sous le seuil": ([{"tension_systolique": 110}, {"tension_systolique": 120}], {"tension_systolique": 130}),
        }
        for nom, (historique, actuelles) in cas.items():
            with self.subTest(nom):
                self.assertEqual(alertes.signes_d_evolution(historique, actuelles), [])

    def test_niveau_et_fusion(self):
        a = alertes.Signe("Fièvre", "frissons", "surveiller", "texte")
        b = alertes.Signe("Fièvre", "T 39,8", "signaler", "constantes")
        c = alertes.Signe("Chute", "chute", "surveiller", "ia")
        fusion = alertes.fusionner([a, c], [b])
        self.assertEqual([(s.nom, s.gravite) for s in fusion], [("Fièvre", "signaler"), ("Chute", "surveiller")])
        self.assertEqual(alertes.niveau(fusion), "signaler")
        self.assertEqual(alertes.niveau([]), "ras")


# --- Compte rendu intelligent : IA et garde-fous -------------------------------------------------------


def reponse_ia(**donnees):
    return mock.patch("infirmiers.ia_soin._appel", return_value=ia_client.ResultatIA(ia_client.OK, donnees))


class GardeFousIATests(SimpleTestCase):
    NOTE = "Le pourtour de la plaie est enflammé. Thermomètre à 38 et 6. Tension 16/10."

    def test_constantes_acceptees(self):
        brut = {
            "temperature": {"valeur": 38.6, "extrait": "Thermomètre à 38 et 6"},
            "tension_systolique": {"valeur": 160, "extrait": "Tension 16/10"},
        }
        self.assertEqual(ia_soin.constantes_valides(brut, self.NOTE), {
            "temperature": (38.6, "Thermomètre à 38 et 6"), "tension_systolique": (160.0, "Tension 16/10"),
        })

    def test_constantes_refusees(self):
        cas = {
            "chiffre inventé": {"temperature": {"valeur": 39.2, "extrait": "Thermomètre à 38 et 6"}},
            "extrait absent de la note": {"frequence_cardiaque": {"valeur": 90, "extrait": "pouls 90"}},
            "valeur improbable": {"saturation_oxygene": {"valeur": 160, "extrait": "Tension 16/10"}},
            "constante inconnue": {"glycemie": {"valeur": 1.2, "extrait": "Tension 16/10"}},
            "booléen": {"temperature": {"valeur": True, "extrait": "Thermomètre à 38 et 6"}},
            "format libre": {"temperature": "38,6"},
        }
        for nom, brut in cas.items():
            with self.subTest(nom):
                self.assertEqual(ia_soin.constantes_valides(brut, self.NOTE), {})

    def test_le_nom_du_patient_n_est_pas_envoye(self):
        note = ia_soin.anonymiser_note("Mme Trabelsi va mieux, appeler Amel au 20 111 222.", ("Amel", "Trabelsi"))
        self.assertNotIn("Trabelsi", note)
        self.assertNotIn("Amel", note)
        self.assertNotIn("111", note)

    def test_signes_de_l_ia_valides(self):
        note = "Le pourtour de la plaie a un aspect inquiétant. Tension 16/10."  # formulation inconnue des règles
        signes = [
            {"nom": "Signes d'infection de la plaie", "extrait": "pourtour de la plaie a un aspect inquiétant"},
            {"nom": "Cancer", "extrait": "pourtour de la plaie a un aspect inquiétant"},  # hors catalogue
            {"nom": "Chute", "extrait": "est tombée dans la cuisine"},  # citation inventée
        ]
        with reponse_ia(constantes={}, signes=signes):
            analyse = ia_soin.analyser(note)
        self.assertEqual(analyse.statut_ia, "ok")
        self.assertEqual([s.nom for s in analyse.signes if s.origine == "ia"], ["Signes d'infection de la plaie"])
        self.assertEqual(analyse.niveau, "signaler")

    def test_les_regles_gardent_la_priorite_sur_les_constantes(self):
        with reponse_ia(constantes={"tension_systolique": {"valeur": 16, "extrait": "Tension 16/10"}}, signes=[]):
            analyse = ia_soin.analyser(self.NOTE)
        self.assertEqual(analyse.constantes["tension_systolique"][0], 160.0)

    def test_panne_de_l_ia_analyse_par_regles(self):
        with mock.patch("infirmiers.ia_soin._appel", return_value=ia_client.ResultatIA(ia_client.DELAI)):
            analyse = ia_soin.analyser("Patiente essoufflée. T 38,4.")
        self.assertEqual(analyse.statut_ia, "delai")
        self.assertFalse(analyse.ia_utilisee)
        self.assertIn("règles uniquement", analyse.message_ia)
        self.assertEqual({s.nom for s in analyse.signes}, {"Difficulté respiratoire", "Fièvre"})

    def test_sans_ia(self):
        analyse = ia_soin.analyser("Injection faite, RAS. T 37,1.", utiliser_ia=False)
        self.assertEqual((analyse.niveau, analyse.libelle, analyse.signes), ("ras", "RAS", []))

    def test_valeur_corrigee_par_l_infirmier(self):
        """38,4 écrit dans la note mais corrigé en 37,6 : ni seuil de fièvre ni signe tiré de « T 38,4 »."""
        analyse = ia_soin.analyser("Frissons. T 38,4.", constantes={"temperature": Decimal("37.6")}, utiliser_ia=False)
        self.assertEqual([(s.nom, s.extrait) for s in analyse.signes], [("Fièvre", "Frissons")])

    def test_evolution_prise_en_compte(self):
        historique = [{"saturation_oxygene": 97}, {"saturation_oxygene": 95}]
        analyse = ia_soin.analyser("RAS. Sat 93 %.", historique=historique, utiliser_ia=False)
        self.assertIn("Saturation en baisse", {s.nom for s in analyse.signes})


class TerminerAvecAnalyseTests(SansBaseMixin, SimpleTestCase):
    def test_signes_enregistres_dans_l_intervention(self):
        it = une_intervention()
        it.accepter(un_infirmier(), plus_tard())
        analyse = ia_soin.analyser("Patiente essoufflée. T 38,4.", utiliser_ia=False)
        it.terminer("Patiente essoufflée. T 38,4.", ConstantesVitales(temperature=Decimal("38.4")), analyse=analyse)
        self.assertEqual((it.niveau_alerte, it.analyse_ia), ("signaler", "non_configuree"))
        self.assertTrue(it.a_signaler)
        self.assertEqual({(s.nom, s.origine) for s in it.signes_alerte}, {("Difficulté respiratoire", "texte"), ("Fièvre", "constantes")})
        self.assertEqual(it.releves(), {"temperature": 38.4})

    def test_sans_analyse_rien_n_est_note(self):
        it = une_intervention()
        it.accepter(un_infirmier(), plus_tard())
        it.terminer("Fait.")
        self.assertEqual((it.niveau_alerte, it.signes_alerte, it.releves()), ("", [], {}))


# --- Espace patient : demandes de soins à domicile -----------------------------------------------------


class DemandeSoinFormTests(SimpleTestCase):
    def setUp(self):
        self.patient = Patient(pk=ObjectId(), user=User(username="amel"), adresse="7 rue de Rome", ville="La Marsa")
        # Aucun accès à la base : l'unicité n'est pas en jeu et la consultation reste vide.
        p = mock.patch.object(DemandeSoinForm, "validate_unique", lambda form: None)
        p.start()
        self.addCleanup(p.stop)

    def donnees(self, **kw):
        valeurs = {
            "type_soin": "injection", "description": "", "date_souhaitee": (timezone.localdate() + datetime.timedelta(days=1)).isoformat(),
            "moment": "matin", "adresse": "7 rue de Rome", "ville": "La Marsa",
        }
        valeurs.update(kw)
        return valeurs

    def test_adresse_et_ville_du_patient_proposees(self):
        form = DemandeSoinForm(patient=self.patient)
        self.assertEqual((form.initial["adresse"], form.initial["ville"]), ("7 rue de Rome", "La Marsa"))
        self.assertEqual(form.fields["date_souhaitee"].widget.attrs["min"], timezone.localdate().isoformat())

    def test_la_demande_appartient_au_patient(self):
        form = DemandeSoinForm(self.donnees(), patient=self.patient)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.instance.patient, self.patient)
        self.assertEqual(form.instance.statut, "demandee")

    def test_date_passee_refusee(self):
        form = DemandeSoinForm(self.donnees(date_souhaitee=(timezone.localdate() - datetime.timedelta(days=1)).isoformat()), patient=self.patient)
        self.assertFalse(form.is_valid())
        self.assertIn("date_souhaitee", form.errors)

    def test_champs_obligatoires(self):
        form = DemandeSoinForm(self.donnees(type_soin="", adresse="", ville=""), patient=self.patient)
        self.assertFalse(form.is_valid())
        self.assertTrue({"type_soin", "adresse", "ville"} <= set(form.errors))

    def test_le_patient_ne_choisit_ni_infirmier_ni_statut(self):
        self.assertFalse({"infirmier", "statut", "date_prevue", "compte_rendu"} & set(DemandeSoinForm.base_fields))


class EspacePatientTests(SimpleTestCase):
    VUES = ("soins", "soin_demander", "soin", "soin_modifier", "soin_supprimer", "soin_annuler")

    def appeler(self, nom, user):
        requete = RequestFactory().get("/infirmiers/soins/")
        requete.user = user
        args = () if nom in ("soins", "soin_demander") else ("x",)
        return getattr(views_patient, nom)(requete, *args)

    def test_adresses(self):
        pk = str(ObjectId())
        cas = {
            "/infirmiers/soins/": "soins",
            "/infirmiers/soins/nouveau/": "soin_demander",
            f"/infirmiers/soins/{pk}/": "soin",
            f"/infirmiers/soins/{pk}/modifier/": "soin_modifier",
            f"/infirmiers/soins/{pk}/supprimer/": "soin_supprimer",
            f"/infirmiers/soins/{pk}/annuler/": "soin_annuler",
        }
        for url, nom in cas.items():
            with self.subTest(url=url):
                self.assertEqual(resolve(url).view_name, f"infirmiers:{nom}")

    def test_anonyme_renvoye_vers_la_connexion(self):
        for nom in self.VUES:
            with self.subTest(vue=nom):
                self.assertEqual(self.appeler(nom, AnonymousUser()).status_code, 302)

    def test_reserve_aux_patients(self):
        infirmier = User(username="sami", role="infirmier")  # jamais enregistré : aucun profil patient
        for nom in self.VUES:
            with self.subTest(vue=nom):
                with self.assertRaises(PermissionDenied):
                    self.appeler(nom, infirmier)

    def test_infirmiers_disponibles(self):
        tunis = un_infirmier(ville="Tunis", zones=[], soins=[TypeSoin.INJECTION])
        tous_soins = un_infirmier(ville="La Marsa", zones=["Tunis"], soins=[])
        non_valide = un_infirmier(valide=False)
        with mock.patch.object(Infirmier.objects, "select_related") as requete:
            requete.return_value.filter.return_value = [tunis, tous_soins, non_valide]
            self.assertEqual(views_patient.infirmiers_disponibles(une_intervention(ville="tunis")), [tunis, tous_soins])
            self.assertEqual(views_patient.infirmiers_disponibles(une_intervention(type_soin=TypeSoin.PERFUSION)), [tous_soins])


# --- E-mails ---------------------------------------------------------------------------------------------


class NotificationsTests(SimpleTestCase):
    """Le lanceur de tests remplace l'envoi réel par une boîte en mémoire (mail.outbox)."""

    LIEN = "https://mediconnect.exemple/infirmiers/soins/1/"
    MEDICAL = ("Injection", "injection", "Lovenox", "essouffl", "hospitalis", "38,4")

    def setUp(self):
        mail.outbox = []
        self.it = une_intervention(
            description="Lovenox chaque matin", statut="acceptee", infirmier=un_infirmier(),
            date_prevue=timezone.make_aware(datetime.datetime(2026, 11, 2, 9, 30)),
            compte_rendu="Injection faite, patiente essoufflée, T 38,4", motif_annulation="Patiente hospitalisée",
            realisee_le=timezone.make_aware(datetime.datetime(2026, 11, 2, 9, 45)),
        )
        self.it.patient.user.email = "amel@exemple.tn"
        self.it.infirmier.user.email = "sami@exemple.tn"

    def verifier(self, envoye, destinataire, objet):
        self.assertTrue(envoye)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [destinataire])
        self.assertEqual(message.subject, f"{objet} — MediConnect")
        html = message.alternatives[0][0]
        self.assertEqual(message.alternatives[0][1], "text/html")
        for contenu in (message.body, html):
            self.assertIn(self.LIEN, contenu)
            for mot in self.MEDICAL:
                self.assertNotIn(mot, contenu)
        return message

    def test_passage_accepte(self):
        message = self.verifier(notifications.passage_fixe(self.it, self.LIEN), "amel@exemple.tn", "Un infirmier a accepté votre demande")
        self.assertIn("Sami Ben Ali", message.body)
        self.assertIn("21000000", message.body)
        self.assertIn("09:30", message.body)

    def test_passage_deplace(self):
        ancien = timezone.make_aware(datetime.datetime(2026, 11, 1, 14, 0))
        message = self.verifier(notifications.passage_fixe(self.it, self.LIEN, ancien=ancien), "amel@exemple.tn", "Le passage de l'infirmier a changé d'heure")
        self.assertIn("14:00", message.body)
        self.assertIn("09:30", message.body)

    def test_desistement(self):
        infirmier, ancien = self.it.infirmier, self.it.date_prevue
        self.it.infirmier, self.it.date_prevue = None, None
        message = self.verifier(notifications.passage_libere(self.it, self.LIEN, infirmier, ancien), "amel@exemple.tn", "Votre demande est de nouveau proposée")
        self.assertIn("Sami Ben Ali", message.body)

    def test_annulation_par_l_infirmier_sans_le_motif(self):
        self.verifier(notifications.passage_annule(self.it, self.LIEN), "amel@exemple.tn", "Le passage de l'infirmier est annulé")

    def test_compte_rendu_sans_son_contenu(self):
        self.verifier(notifications.compte_rendu_disponible(self.it, self.LIEN), "amel@exemple.tn", "Le compte rendu de votre soin est disponible")

    def test_annulation_par_le_patient_envoyee_a_l_infirmier(self):
        message = self.verifier(notifications.annule_par_le_patient(self.it, self.LIEN), "sami@exemple.tn", "Un passage a été annulé")
        self.assertNotIn("Amel", message.body.split(",", 1)[1])  # seul l'infirmier est salué ; le patient n'est pas nommé

    def test_rien_sans_adresse_ou_sans_passage(self):
        self.it.patient.user.email = ""
        self.assertFalse(notifications.passage_fixe(self.it, self.LIEN))
        self.it.patient.user.email = "amel@exemple.tn"
        self.it.date_prevue = None
        self.assertFalse(notifications.passage_fixe(self.it, self.LIEN))
        self.assertFalse(notifications.annule_par_le_patient(self.it, self.LIEN))
        self.assertEqual(mail.outbox, [])

    def test_une_panne_d_envoi_ne_leve_pas_d_erreur(self):
        with mock.patch("infirmiers.notifications.EmailMultiAlternatives.send", side_effect=ConnectionRefusedError):
            with self.assertLogs("infirmiers.notifications", level="ERROR"):
                self.assertFalse(notifications.passage_fixe(self.it, self.LIEN))


class ValidationAdminTests(SimpleTestCase):
    def test_actions_de_validation(self):
        modele_admin = admin.site._registry[Infirmier]
        a_valider, deja_valide = un_infirmier(valide=False), un_infirmier(valide=True)
        requete = mock.Mock()
        requete.select_related.return_value = [a_valider, deja_valide]
        with mock.patch.object(User, "save") as enregistrer, mock.patch.object(modele_admin, "message_user") as message:
            modele_admin.valider_comptes(None, requete)
        self.assertTrue(a_valider.user.est_valide)
        enregistrer.assert_called_once_with(update_fields=["est_valide"])  # seul le compte qui change est enregistré
        message.assert_called_once_with(None, "1 compte(s) validé(s).")
        self.assertEqual(modele_admin.actions, ["valider_comptes", "retirer_validation"])


# --- Planning : pas de double réservation --------------------------------------------------------------


class PlanningTests(SimpleTestCase):
    def setUp(self):
        self.dix_heures = timezone.make_aware(datetime.datetime(2026, 11, 2, 10, 0))

    def a(self, minutes):
        return self.dix_heures + datetime.timedelta(minutes=minutes)

    def test_conflit_a_moins_de_trente_minutes(self):
        self.assertEqual(passage_en_conflit(self.a(20), [self.dix_heures]), self.dix_heures)
        self.assertEqual(passage_en_conflit(self.a(-29), [self.dix_heures]), self.dix_heures)
        self.assertIsNone(passage_en_conflit(self.a(30), [self.dix_heures]))
        self.assertIsNone(passage_en_conflit(self.a(-30), [self.dix_heures]))
        self.assertIsNone(passage_en_conflit(self.dix_heures, []))

    def test_prochain_creneau_libre(self):
        self.assertEqual(prochain_creneau_libre(self.a(0), []), self.a(0))
        self.assertEqual(prochain_creneau_libre(self.a(10), [self.a(0)]), self.a(30))
        # 10:00 et 10:30 sont pris : on saute les deux
        self.assertEqual(prochain_creneau_libre(self.a(5), [self.a(30), self.a(0)]), self.a(60))

    def test_message_de_la_vue(self):
        with mock.patch.object(InterventionDomicile.objects, "passages_autour", return_value=[self.dix_heures]) as passages:
            message = views._conflit_de_planning(un_infirmier(), self.a(15), exclure="x")
        self.assertIn("déjà un passage à 10:00", message)
        self.assertIn("Prochain créneau libre : 02/11 à 10:30", message)
        self.assertEqual(passages.call_args.args[2], "x")  # l'intervention déplacée ne se gêne pas elle-même
        with mock.patch.object(InterventionDomicile.objects, "passages_autour", return_value=[]):
            self.assertIsNone(views._conflit_de_planning(un_infirmier(), self.a(15)))


# --- Dossier du patient : constantes reprises en mesures de santé ------------------------------------------


class DossierPatientTests(SimpleTestCase):
    def realisee(self, **constantes):
        it = une_intervention(statut="realisee", infirmier=un_infirmier(), realisee_le=timezone.make_aware(datetime.datetime(2026, 11, 2, 10, 17, 42)))
        it.constantes = ConstantesVitales(**constantes) if constantes else None
        return it

    def test_une_mesure_par_constante(self):
        mesures = dossier.mesures_du_passage(self.realisee(
            temperature=Decimal("38.2"), tension_systolique=160, tension_diastolique=98, frequence_cardiaque=92, saturation_oxygene=95,
        ))
        self.assertEqual(
            sorted((m.type, m.valeur, m.valeur2) for m in mesures),
            [("frequence", 92.0, None), ("saturation", 95.0, None), ("temperature", 38.2, None), ("tension", 160.0, 98.0)],
        )
        m = mesures[0]
        self.assertEqual(m.mesure_le.second, 0)  # à la minute, comme les mesures saisies par le patient
        self.assertEqual(m.note, "Relevé par l'infirmier Sami Ben Ali lors d'un soin à domicile")

    def test_rien_a_reprendre(self):
        self.assertEqual(dossier.mesures_du_passage(self.realisee()), [])
        self.assertEqual(dossier.mesures_du_passage(self.realisee(tension_systolique=160)), [])  # tension incomplète
        en_cours = self.realisee(temperature=Decimal("37"))
        en_cours.statut = "acceptee"
        self.assertEqual(dossier.mesures_du_passage(en_cours), [])

    def test_une_mesure_invalide_ne_bloque_pas(self):
        with mock.patch.object(Mesure, "full_clean", side_effect=ValidationError({"mesure_le": "doublon"})), \
                mock.patch.object(Mesure, "save") as enregistrer:
            self.assertEqual(dossier.enregistrer_mesures(self.realisee(temperature=Decimal("37.5"))), 0)
        enregistrer.assert_not_called()

    def test_historique_sans_doublon(self):
        """Le passage et la mesure qui en est tirée (même minute) ne comptent qu'une fois."""
        passage = self.realisee(tension_systolique=150, tension_diastolique=90)
        meme_minute = Mesure(type="tension", valeur=150, valeur2=90, mesure_le=passage.realisee_le.replace(second=0))
        plus_tot = Mesure(type="tension", valeur=141, valeur2=88, mesure_le=passage.realisee_le - datetime.timedelta(days=2))
        passages = mock.Mock()
        passages.exclude.return_value = [passage]
        with mock.patch.object(InterventionDomicile.objects, "filter", return_value=passages), \
                mock.patch.object(Mesure.objects, "filter", return_value=[meme_minute, plus_tot]):
            historique = dossier.historique(une_intervention())
        self.assertEqual(historique, [
            {"tension_systolique": 141, "tension_diastolique": 88},
            {"tension_systolique": 150.0, "tension_diastolique": 90.0},
        ])
