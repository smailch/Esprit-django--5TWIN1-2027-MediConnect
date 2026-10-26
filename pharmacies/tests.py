import datetime
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bson import ObjectId
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from core.accessibilite import verifier_html
from patients.models import Allergie, Consultation, Patient

from . import permissions, views
from .forms import OrdonnanceForm, PharmacieForm, TransmissionForm
from .models import DUREE_VALIDITE_JOURS, MAX_LIGNES, Ordonnance, Pharmacie
from .permissions import ADMIN, MEDECIN, MESSAGE_EN_ATTENTE, PATIENT, PHARMACIE, espace_de, espace_requis

User = get_user_model()
RACINE = Path(__file__).resolve().parent.parent
AUJOURDHUI = timezone.localdate()
S = Ordonnance.Statut


def un_user(**kw):
    """Utilisateur non enregistré (aucun accès à la base)."""
    valeurs = {"username": "u", "is_active": True, "est_valide": True}
    valeurs.update(kw)
    return User(**valeurs)


def un_patient():
    patient = Patient(
        user=un_user(username="yassine", first_name="Yassine", last_name="Khelifi"),
        date_naissance=datetime.date(1992, 3, 14), sexe="H", telephone="22456789", ville="Tunis",
    )
    patient.pk = ObjectId()
    return patient


def un_compte(**kw):
    """Utilisateur non enregistré mais avec un identifiant, comme après son enregistrement."""
    user = un_user(**kw)
    user.pk = ObjectId()
    return user


def une_pharmacie(**kw):
    valeurs = {"user": un_compte(username="lac", role="pharmacie"), "nom": "Pharmacie du Lac", "adresse": "12 rue du Lac",
               "ville": "Tunis", "telephone": "71 960 123"}
    valeurs.update(kw)
    pharmacie = Pharmacie(**valeurs)
    pharmacie.pk = ObjectId()
    return pharmacie


def une_ordonnance(**kw):
    valeurs = {"patient": un_patient(), "prescripteur_nom": "Dr Sara Benali", "date_emission": AUJOURDHUI,
               "medicaments": "Amoxicilline 1 g, matin et soir, 7 jours\nParacétamol 1 g si fièvre"}
    valeurs.update(kw)
    ordonnance = Ordonnance(**valeurs)
    ordonnance.pk = ObjectId()
    return ordonnance


def avec_messages(requete):
    """Les vues envoient des messages : il leur faut une session et un stockage."""
    requete.session = {}
    requete._messages = FallbackStorage(requete)
    return requete


# --- Modèle Ordonnance ---------------------------------------------------------------------------------------


class OrdonnanceModeleTests(SimpleTestCase):
    def test_une_ligne_par_medicament_sans_puces_ni_lignes_vides(self):
        o = une_ordonnance(medicaments="- Amoxicilline\n\n• Paracétamol  \n   ")
        self.assertEqual(o.lignes, ["Amoxicilline", "Paracétamol"])

    def test_clean_nettoie_le_texte(self):
        o = une_ordonnance(medicaments="- Amoxicilline\n\n• Paracétamol")
        o.clean()
        self.assertEqual(o.medicaments, "Amoxicilline\nParacétamol")

    def test_au_moins_un_medicament(self):
        with self.assertRaises(ValidationError) as ctx:
            une_ordonnance(medicaments="  \n - ").clean()
        self.assertIn("medicaments", ctx.exception.message_dict)

    def test_nombre_de_lignes_limite(self):
        with self.assertRaises(ValidationError) as ctx:
            une_ordonnance(medicaments="\n".join(f"Médicament {i}" for i in range(MAX_LIGNES + 1))).clean()
        self.assertIn("medicaments", ctx.exception.message_dict)

    def test_pas_de_date_dans_le_futur(self):
        with self.assertRaises(ValidationError) as ctx:
            une_ordonnance(date_emission=AUJOURDHUI + datetime.timedelta(days=1)).clean()
        self.assertIn("date_emission", ctx.exception.message_dict)

    def test_la_validite_suit_la_date_de_l_ordonnance(self):
        with self.assertRaises(ValidationError) as ctx:
            une_ordonnance(valide_jusqu_au=AUJOURDHUI - datetime.timedelta(days=1)).clean()
        self.assertIn("valide_jusqu_au", ctx.exception.message_dict)

    def test_la_consultation_doit_etre_celle_du_meme_patient(self):
        autre = Consultation(patient=un_patient(), medecin_nom="Dr X", resume="…")
        autre.pk = ObjectId()
        with self.assertRaises(ValidationError) as ctx:
            une_ordonnance(consultation=autre).clean()
        self.assertIn("consultation", ctx.exception.message_dict)

    def test_ordonnance_valide(self):
        o = une_ordonnance()
        consultation = Consultation(patient=o.patient, medecin_nom="Dr X", resume="…")
        consultation.pk = ObjectId()
        o.consultation = consultation
        o.clean()  # aucune erreur

    def test_validite_par_defaut_trois_mois(self):
        o = une_ordonnance()
        o.appliquer_validite_par_defaut()
        self.assertEqual(o.valide_jusqu_au, AUJOURDHUI + datetime.timedelta(days=DUREE_VALIDITE_JOURS))

    def test_une_validite_saisie_est_gardee(self):
        fin = AUJOURDHUI + datetime.timedelta(days=10)
        o = une_ordonnance(valide_jusqu_au=fin)
        o.appliquer_validite_par_defaut()
        self.assertEqual(o.valide_jusqu_au, fin)

    def test_la_validite_est_fixee_a_l_enregistrement(self):
        o = une_ordonnance()
        with mock.patch("django.db.models.Model.save") as enregistrer:
            o.save()
        enregistrer.assert_called_once()
        self.assertEqual(o.valide_jusqu_au, AUJOURDHUI + datetime.timedelta(days=DUREE_VALIDITE_JOURS))

    def test_expiration(self):
        self.assertTrue(une_ordonnance(valide_jusqu_au=AUJOURDHUI - datetime.timedelta(days=1)).est_expiree)
        self.assertFalse(une_ordonnance(valide_jusqu_au=AUJOURDHUI).est_expiree)
        self.assertFalse(une_ordonnance(valide_jusqu_au=None).est_expiree)

    def test_reference_courte(self):
        o = une_ordonnance()
        self.assertEqual(o.reference, "ORD-" + str(o.pk)[-6:].upper())
        self.assertEqual(Ordonnance().reference, "ORD-?")

    def test_droits_selon_le_statut(self):
        attendus = {  # statut: (modifiable, supprimable, annulable, transmissible)
            S.EMISE: (True, True, True, True),
            S.TRANSMISE: (True, True, True, True),
            S.EN_PREPARATION: (False, False, True, False),
            S.PRETE: (False, False, True, False),
            S.DELIVREE: (False, False, False, False),
            S.ANNULEE: (False, True, False, False),
        }
        for statut, (modifiable, supprimable, annulable, transmissible) in attendus.items():
            o = une_ordonnance(statut=statut)
            with self.subTest(statut=statut):
                self.assertEqual(
                    (o.est_modifiable, o.est_supprimable, o.est_annulable, o.est_transmissible),
                    (modifiable, supprimable, annulable, transmissible),
                )

    def test_une_ordonnance_expiree_ne_se_transmet_plus(self):
        self.assertFalse(une_ordonnance(valide_jusqu_au=AUJOURDHUI - datetime.timedelta(days=1)).est_transmissible)

    def test_etape_du_parcours(self):
        self.assertEqual(une_ordonnance(statut=S.EMISE).etape, 0)
        self.assertEqual(une_ordonnance(statut=S.DELIVREE).etape, 4)
        self.assertIsNone(une_ordonnance(statut=S.ANNULEE).etape)


class OrdonnanceCycleDeVieTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(Ordonnance, "save")
        self.save = p.start()
        self.addCleanup(p.stop)

    def test_la_pharmacie_avance_d_une_etape_a_la_fois(self):
        o = une_ordonnance(statut=S.TRANSMISE)
        self.assertEqual(o.avancer(), S.EN_PREPARATION)
        self.assertEqual(o.avancer(), S.PRETE)
        self.assertIsNone(o.delivree_le)
        self.assertEqual(o.avancer(), S.DELIVREE)
        self.assertIsNotNone(o.delivree_le)
        self.assertEqual(self.save.call_count, 3)
        self.assertIn("delivree_le", self.save.call_args.kwargs["update_fields"])

    def test_pas_d_avancee_hors_du_circuit_de_la_pharmacie(self):
        for statut in (S.EMISE, S.DELIVREE, S.ANNULEE):
            with self.subTest(statut=statut), self.assertRaises(ValueError):
                une_ordonnance(statut=statut).avancer()
        self.save.assert_not_called()

    def test_une_ordonnance_expiree_n_est_pas_delivree(self):
        o = une_ordonnance(statut=S.PRETE, valide_jusqu_au=AUJOURDHUI - datetime.timedelta(days=1))
        with self.assertRaisesMessage(ValueError, "expiré"):
            o.avancer()
        self.assertEqual(o.statut, S.PRETE)



# --- Modèle Pharmacie --------------------------------------------------------------------------------------


class PharmacieModeleTests(SimpleTestCase):
    def test_le_compte_doit_avoir_le_role_pharmacie(self):
        with self.assertRaises(ValidationError) as ctx:
            une_pharmacie(user=un_compte(role="patient")).clean()
        self.assertIn("user", ctx.exception.message_dict)
        une_pharmacie().clean()  # rôle « pharmacie » : accepté

    def test_espaces_superflus_retires_du_nom(self):
        p = une_pharmacie(nom="  Pharmacie   du   Lac ")
        p.clean()
        self.assertEqual(p.nom, "Pharmacie du Lac")

    def test_telephone_controle(self):
        champ = Pharmacie._meta.get_field("telephone")
        for bon in ("71 960 123", "+216 71 960 123", "22456789"):
            champ.run_validators(bon)
        for mauvais in ("abc", "12", "71-960-123", "<script>"):
            with self.subTest(numero=mauvais), self.assertRaises(ValidationError):
                champ.run_validators(mauvais)

    def test_affichage(self):
        self.assertEqual(str(une_pharmacie()), "Pharmacie du Lac")


# --- Droits d'accès ---------------------------------------------------------------------------------------


class EspacesTests(SimpleTestCase):
    def test_administrateur(self):
        self.assertEqual(espace_de(un_user(is_staff=True)), ADMIN)
        self.assertEqual(espace_de(un_user(role="admin")), ADMIN)

    def test_medecin_valide_seulement(self):
        self.assertEqual(espace_de(un_user(role="medecin")), MEDECIN)
        self.assertEqual(espace_de(un_user(role="medecin", est_valide=False)), "")

    def test_pharmacie_validee_et_avec_sa_fiche(self):
        with mock.patch.object(permissions, "pharmacie_de", return_value=une_pharmacie()):
            self.assertEqual(espace_de(un_user(role="pharmacie")), PHARMACIE)
            self.assertEqual(espace_de(un_user(role="pharmacie", est_valide=False)), "")
        with mock.patch.object(permissions, "pharmacie_de", return_value=None):
            self.assertEqual(espace_de(un_user(role="pharmacie")), "")

    def test_patient(self):
        with mock.patch.object(permissions, "patient_de", return_value=un_patient()):
            self.assertEqual(espace_de(un_user(role="patient")), PATIENT)
        with mock.patch.object(permissions, "patient_de", return_value=None):
            self.assertEqual(espace_de(un_user(role="laboratoire")), "")

    def test_anonyme_et_compte_desactive(self):
        self.assertEqual(espace_de(AnonymousUser()), "")
        self.assertEqual(espace_de(un_user(is_staff=True, is_active=False)), "")


class DecorateurTests(SimpleTestCase):
    def appeler(self, user, *autorises):
        @espace_requis(*autorises)
        def vue(request):
            return SimpleNamespace(espace=request.espace)

        requete = RequestFactory().get("/pharmacies/ordonnances/?statut=prete")
        requete.user = user
        return vue(requete)

    def test_anonyme_renvoye_vers_la_connexion_avec_retour_prevu(self):
        reponse = self.appeler(AnonymousUser(), PATIENT)
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/?next="))
        self.assertIn("ordonnances", reponse["Location"])

    def test_un_autre_espace_recoit_une_interdiction(self):
        with mock.patch.object(permissions, "patient_de", return_value=un_patient()):
            with self.assertRaises(PermissionDenied):
                self.appeler(un_user(role="patient"), PHARMACIE)

    def test_une_pharmacie_non_validee_est_prevenue(self):
        with self.assertRaisesMessage(PermissionDenied, MESSAGE_EN_ATTENTE):
            self.appeler(un_user(role="pharmacie", est_valide=False), PHARMACIE)

    def test_l_espace_est_transmis_a_la_vue(self):
        self.assertEqual(self.appeler(un_user(is_staff=True), ADMIN, MEDECIN).espace, ADMIN)


class UrlsTests(SimpleTestCase):
    def test_adresses(self):
        pk = "a" * 24
        self.assertEqual(reverse("pharmacies:pharmacies"), "/pharmacies/")
        self.assertEqual(reverse("pharmacies:ma_pharmacie"), "/pharmacies/ma-pharmacie/")
        self.assertEqual(reverse("pharmacies:ordonnances"), "/pharmacies/ordonnances/")
        self.assertEqual(reverse("pharmacies:ordonnance_creer", args=[pk]), f"/pharmacies/ordonnances/nouvelle/{pk}/")
        self.assertEqual(reverse("pharmacies:ordonnance_avancer", args=[pk]), f"/pharmacies/ordonnances/{pk}/avancer/")
        self.assertEqual(reverse("pharmacies:pharmacie_modifier", args=[pk]), f"/pharmacies/{pk}/modifier/")

    def test_les_adresses_fixes_ne_sont_pas_prises_pour_un_identifiant(self):
        self.assertIs(resolve("/pharmacies/ordonnances/").func, views.ordonnances)
        self.assertIs(resolve("/pharmacies/ma-pharmacie/").func, views.ma_pharmacie)
        self.assertIs(resolve("/pharmacies/nouvelle/").func, views.pharmacie_creer)
        self.assertIs(resolve("/pharmacies/abc/").func, views.pharmacie_detail)

    def test_visiteur_anonyme_renvoye_vers_la_connexion(self):
        for url in ("/pharmacies/", "/pharmacies/ordonnances/", "/pharmacies/ordonnances/abc/", "/pharmacies/abc/modifier/"):
            with self.subTest(url=url):
                reponse = self.client.get(url)
                self.assertEqual(reponse.status_code, 302)
                self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))


class VisibiliteTests(SimpleTestCase):
    """Chaque compte ne voit que ses ordonnances : protection contre l'accès direct par identifiant (OWASP A01)."""

    def requete(self, espace):
        requete = RequestFactory().get("/")
        requete.user, requete.espace = un_user(), espace
        return requete

    def test_filtre_selon_l_espace(self):
        patient, pharmacie = un_patient(), une_pharmacie()
        with mock.patch.object(Ordonnance.objects, "select_related") as base, \
                mock.patch.object(views, "patient_de", return_value=patient), \
                mock.patch.object(views, "pharmacie_de", return_value=pharmacie):
            views.ordonnances_visibles(self.requete(PATIENT))
            base.return_value.filter.assert_called_with(patient=patient)
            views.ordonnances_visibles(self.requete(PHARMACIE))
            base.return_value.filter.assert_called_with(pharmacie=pharmacie)
            base.return_value.filter.reset_mock()
            for espace in (ADMIN, MEDECIN):
                self.assertIs(views.ordonnances_visibles(self.requete(espace)), base.return_value)
            base.return_value.filter.assert_not_called()

    def test_espace_inconnu_refuse(self):
        with mock.patch.object(Ordonnance.objects, "select_related"), self.assertRaises(PermissionDenied):
            views.ordonnances_visibles(self.requete(""))

    def test_les_vues_cherchent_toujours_dans_les_ordonnances_visibles(self):
        for nom in ("ordonnance_detail", "ordonnance_modifier", "ordonnance_supprimer", "ordonnance_annuler",
                    "ordonnance_transmettre", "ordonnance_avancer"):
            with self.subTest(vue=nom):
                self.assertIn("objet_ou_404(ordonnances_visibles(request), pk=pk)", inspect.getsource(getattr(views, nom)))


# --- Vues (requêtes simulées, base remplacée par des objets en mémoire) ----------------------------------------


class VuesTests(SimpleTestCase):
    def requete(self, espace, methode="get", donnees=None, user=None):
        requete = getattr(RequestFactory(), methode)("/pharmacies/", donnees or {})
        requete.user = user or un_user(role=espace)
        return avec_messages(requete)

    def appeler(self, vue, espace, *args, methode="get", donnees=None, objet=None):
        with mock.patch.object(permissions, "espace_de", return_value=espace), \
                mock.patch.object(views, "objet_ou_404", return_value=objet), \
                mock.patch.object(views, "ordonnances_visibles"):
            return vue(self.requete(espace, methode, donnees), *args)

    def test_la_pharmacie_fait_avancer_en_post_uniquement(self):
        o = une_ordonnance(statut=S.TRANSMISE)
        self.assertEqual(self.appeler(views.ordonnance_avancer, PHARMACIE, o.pk, objet=o).status_code, 405)
        with mock.patch.object(Ordonnance, "save"):
            reponse = self.appeler(views.ordonnance_avancer, PHARMACIE, o.pk, methode="post", objet=o)
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(o.statut, S.EN_PREPARATION)

    def test_un_patient_ne_peut_pas_faire_avancer(self):
        with self.assertRaises(PermissionDenied):
            self.appeler(views.ordonnance_avancer, PATIENT, "x", methode="post", objet=une_ordonnance())

    def test_une_avancee_impossible_est_expliquee_sans_erreur_serveur(self):
        o = une_ordonnance(statut=S.DELIVREE)
        reponse = self.appeler(views.ordonnance_avancer, PHARMACIE, o.pk, methode="post", objet=o)
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(o.statut, S.DELIVREE)

    def test_modification_refusee_apres_le_debut_de_la_preparation(self):
        o = une_ordonnance(statut=S.EN_PREPARATION)
        reponse = self.appeler(views.ordonnance_modifier, MEDECIN, o.pk, methode="post", donnees={"medicaments": "X"}, objet=o)
        self.assertEqual(reponse["Location"], reverse("pharmacies:ordonnance_detail", args=[o.pk]))
        self.assertNotEqual(o.medicaments, "X")

    def test_suppression_en_deux_temps(self):
        o = une_ordonnance()
        with mock.patch.object(Ordonnance, "delete") as supprimer:
            self.assertEqual(self.appeler(views.ordonnance_supprimer, ADMIN, o.pk, objet=o).status_code, 200)
            supprimer.assert_not_called()
            reponse = self.appeler(views.ordonnance_supprimer, ADMIN, o.pk, methode="post", objet=o)
            supprimer.assert_called_once()
        self.assertEqual(reponse["Location"], reverse("pharmacies:ordonnances"))

    def test_une_ordonnance_delivree_n_est_jamais_supprimee(self):
        o = une_ordonnance(statut=S.DELIVREE)
        with mock.patch.object(Ordonnance, "delete") as supprimer:
            self.appeler(views.ordonnance_supprimer, ADMIN, o.pk, methode="post", objet=o)
        supprimer.assert_not_called()

    def test_annulation(self):
        o = une_ordonnance(statut=S.PRETE)
        with mock.patch.object(Ordonnance, "save"):
            self.appeler(views.ordonnance_annuler, MEDECIN, o.pk, methode="post", objet=o)
        self.assertEqual(o.statut, S.ANNULEE)

    def test_une_ordonnance_expiree_ne_peut_pas_etre_envoyee(self):
        o = une_ordonnance(valide_jusqu_au=AUJOURDHUI - datetime.timedelta(days=1))
        reponse = self.appeler(views.ordonnance_transmettre, PATIENT, o.pk, objet=o)
        self.assertEqual(reponse.status_code, 302)

    def test_la_transmission_choisit_la_pharmacie(self):
        o, pharmacie = une_ordonnance(), une_pharmacie()
        formulaire = mock.Mock(is_valid=mock.Mock(return_value=True), cleaned_data={"pharmacie": pharmacie})
        with mock.patch.object(views, "TransmissionForm", return_value=formulaire), mock.patch.object(Ordonnance, "save"):
            reponse = self.appeler(views.ordonnance_transmettre, PATIENT, o.pk, methode="post", objet=o)
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual((o.pharmacie, o.statut), (pharmacie, S.TRANSMISE))

    def test_creation_rattachee_a_la_consultation_meme_si_le_formulaire_est_falsifie(self):
        patient = un_patient()
        consultation = Consultation(patient=patient, medecin_nom="Dr Sara Benali", resume="…", prescription="Amoxicilline")
        consultation.pk = ObjectId()
        donnees = {"medicaments": "Amoxicilline 1 g", "date_emission": AUJOURDHUI.isoformat(), "patient": str(ObjectId())}

        def enregistrer(ordonnance, *a, **kw):
            ordonnance.pk = ObjectId()

        with mock.patch.object(Ordonnance, "save", autospec=True, side_effect=enregistrer):
            reponse = self.appeler(views.ordonnance_creer, MEDECIN, consultation.pk, methode="post", donnees=donnees, objet=consultation)
            cree = Ordonnance.save.call_args.args[0]
        self.assertEqual(reponse.status_code, 302)
        self.assertIs(cree.patient, patient)  # le champ « patient » envoyé est ignoré
        self.assertEqual(cree.prescripteur_nom, "Dr Sara Benali")
        self.assertEqual(reponse["Location"], reverse("pharmacies:ordonnance_detail", args=[cree.pk]))

    def test_le_formulaire_de_creation_est_prerempli_avec_la_prescription(self):
        consultation = Consultation(patient=un_patient(), medecin_nom="Dr X", resume="…", prescription="Amoxicilline 1 g")
        consultation.pk = ObjectId()
        with mock.patch.object(views, "render") as rendre:
            self.appeler(views.ordonnance_creer, MEDECIN, consultation.pk, objet=consultation)
        self.assertEqual(rendre.call_args.args[2]["form"].initial["medicaments"], "Amoxicilline 1 g")

    def test_une_pharmacie_ne_modifie_que_sa_fiche(self):
        la_mienne, une_autre = une_pharmacie(), une_pharmacie(nom="Autre")
        with mock.patch.object(views, "pharmacie_de", return_value=la_mienne), self.assertRaises(PermissionDenied):
            self.appeler(views.pharmacie_modifier, PHARMACIE, une_autre.pk, objet=une_autre)

    def test_seul_l_administrateur_ajoute_ou_supprime_une_pharmacie(self):
        for vue in (views.pharmacie_creer, views.pharmacie_supprimer):
            for espace in (PHARMACIE, MEDECIN, PATIENT):
                with self.subTest(vue=vue.__name__, espace=espace), self.assertRaises(PermissionDenied):
                    self.appeler(vue, espace, *(["x"] if vue is views.pharmacie_supprimer else []))

    def test_suppression_d_une_pharmacie_refusee_s_il_reste_des_ordonnances_en_cours(self):
        pharmacie = une_pharmacie()
        with mock.patch.object(Ordonnance.objects, "filter") as filtre, mock.patch.object(Pharmacie, "delete") as supprimer:
            filtre.return_value.count.return_value = 2
            reponse = self.appeler(views.pharmacie_supprimer, ADMIN, pharmacie.pk, methode="post", objet=pharmacie)
        supprimer.assert_not_called()
        self.assertEqual(reponse["Location"], reverse("pharmacies:pharmacie_detail", args=[pharmacie.pk]))


# --- Formulaires -------------------------------------------------------------------------------------------


class FormulairesTests(SimpleTestCase):
    def test_le_patient_et_le_prescripteur_ne_se_saisissent_pas(self):
        self.assertEqual(list(OrdonnanceForm.base_fields), ["medicaments", "instructions", "date_emission", "valide_jusqu_au"])

    def test_champs_de_date_et_style_commun(self):
        form = OrdonnanceForm()
        self.assertEqual(form.fields["date_emission"].widget.input_type, "date")
        self.assertEqual(form.fields["medicaments"].widget.attrs["class"], "field")

    def test_erreurs_du_modele_rattachees_au_bon_champ(self):
        form = OrdonnanceForm({"medicaments": " ", "date_emission": AUJOURDHUI.isoformat()}, instance=une_ordonnance())
        self.assertFalse(form.is_valid())
        self.assertIn("medicaments", form.errors)

    def test_la_pharmacie_ne_change_pas_de_compte(self):
        form = PharmacieForm(instance=une_pharmacie(), avec_compte=False)
        self.assertNotIn("user", form.fields)
        self.assertEqual(form.fields["telephone"].widget.attrs["autocomplete"], "tel")

    def test_la_transmission_ne_propose_que_les_pharmacies_validees(self):
        filtre = TransmissionForm().fields["pharmacie"].queryset.query.where
        self.assertIn("est_valide", str(filtre))
        self.assertIn("is_active", str(filtre))


# --- Pages (rendu des gabarits) ------------------------------------------------------------------------------


class PagesTests(SimpleTestCase):
    def requete(self, espace, page="ordonnances"):
        requete = RequestFactory().get("/pharmacies/")
        requete.user = SimpleNamespace(is_authenticated=True, first_name="Hela", username="h", get_full_name=lambda: "Hela B")
        requete.espace = espace
        requete.resolver_match = SimpleNamespace(url_name=page)
        return requete

    def detail(self, espace, **kw):
        ordonnance = kw.pop("ordonnance", None) or une_ordonnance(**kw)
        return render_to_string("pharmacies/ordonnance_detail.html", {
            "ordonnance": ordonnance,
            "allergies": [Allergie(substance="Pénicilline", gravite="severe", type="medicament")],
            "etapes": [(s, Ordonnance.Statut(s).label) for s in Ordonnance.PARCOURS],
        }, self.requete(espace, "ordonnance_detail"))

    def test_le_patient_envoie_son_ordonnance_et_ne_voit_pas_les_outils_des_autres(self):
        html = self.detail(PATIENT)
        self.assertIn("Envoyer à une pharmacie", html)
        self.assertNotIn("Allergies du patient", html)
        self.assertNotIn("Commencer la préparation", html)
        self.assertNotIn("Annuler l'ordonnance", html)

    def test_la_pharmacie_voit_les_allergies_et_l_action_suivante(self):
        html = self.detail(PHARMACIE, statut=S.TRANSMISE, pharmacie=une_pharmacie())
        self.assertIn("Allergies du patient", html)
        self.assertIn("Pénicilline", html)
        self.assertIn(">Sévère<", html)  # la gravité n'est pas indiquée par la couleur seule
        self.assertIn("Commencer la préparation", html)
        self.assertIn("csrfmiddlewaretoken", html)

    def test_le_prescripteur_modifie_annule_ou_supprime(self):
        html = self.detail(MEDECIN)
        for libelle in ("Modifier", "Annuler l'ordonnance", "Supprimer"):
            self.assertIn(libelle, html)
        self.assertNotIn("Modifier</a>", self.detail(MEDECIN, statut=S.DELIVREE))

    def test_barre_d_etapes_et_ordonnance_annulee(self):
        html = self.detail(PATIENT, statut=S.EN_PREPARATION, pharmacie=une_pharmacie())
        self.assertIn('aria-current="step"', html)
        self.assertEqual(html.count("step-done"), 2)
        annulee = self.detail(PATIENT, statut=S.ANNULEE)
        self.assertIn("a été annulée", annulee)
        self.assertNotIn("stepper", annulee)

    def test_avertissement_ordonnance_expiree(self):
        self.assertIn("a expiré", self.detail(PATIENT, valide_jusqu_au=AUJOURDHUI - datetime.timedelta(days=1)))

    def test_le_patient_est_prevenu_quand_c_est_pret(self):
        self.assertIn("Vos médicaments sont prêts", self.detail(PATIENT, statut=S.PRETE, pharmacie=une_pharmacie()))

    def test_menu_selon_l_espace(self):
        vide = {"page": [], "filtre": None, "a_rediger": []}
        for espace, attendu, absent in (
            (PATIENT, "Mes ordonnances", "Ordonnances reçues"),
            (PHARMACIE, "Ordonnances reçues", "Mes ordonnances"),
            (ADMIN, "Administration", "Ma pharmacie"),
        ):
            html = render_to_string("pharmacies/ordonnances.html", vide, self.requete(espace))
            with self.subTest(espace=espace):
                self.assertIn(attendu, html)
                self.assertNotIn(absent, html)
                self.assertEqual(html.count('aria-current="page"'), 1)

    def test_le_prescripteur_voit_les_consultations_a_traiter(self):
        consultation = Consultation(patient=un_patient(), medecin_nom="Dr X", resume="…", date=timezone.now())
        consultation.pk = ObjectId()
        html = render_to_string("pharmacies/ordonnances.html", {"page": [], "a_rediger": [consultation]}, self.requete(MEDECIN))
        self.assertIn("Rédiger l'ordonnance", html)
        self.assertIn(reverse("pharmacies:ordonnance_creer", args=[consultation.pk]), html)

    def test_etat_vide_explique(self):
        html = render_to_string("pharmacies/ordonnances.html", {"page": []}, self.requete(PATIENT))
        self.assertIn("Vous n'avez pas encore d'ordonnance", html)

    def test_formulaire_erreurs_annoncees(self):
        form = OrdonnanceForm({"medicaments": "", "date_emission": "pas-une-date"}, instance=une_ordonnance())
        form.is_valid()
        html = render_to_string("pharmacies/ordonnance_form.html", {"form": form, "ordonnance": None}, self.requete(MEDECIN, "ordonnance_creer"))
        self.assertIn('role="alert"', html)
        self.assertIn('aria-invalid="true"', html)

    def test_pages_accessibles(self):
        """Structure vérifiée par l'outil d'audit du projet : un seul h1, repères, étiquettes, icônes masquées, th scope…"""
        pharmacie = une_pharmacie(de_garde=True)
        pages = {
            "détail patient": self.detail(PATIENT),
            "détail pharmacie": self.detail(PHARMACIE, statut=S.TRANSMISE, pharmacie=pharmacie),
            "liste": render_to_string("pharmacies/ordonnances.html", {"page": [une_ordonnance()]}, self.requete(MEDECIN)),
            "annuaire": render_to_string("pharmacies/pharmacies.html", {
                "page": [pharmacie], "filtre": views.FiltrePharmaciesForm()}, self.requete(ADMIN, "pharmacies")),
            "fiche": render_to_string("pharmacies/pharmacie_detail.html", {
                "pharmacie": pharmacie, "proprietaire": True, "en_cours": []}, self.requete(ADMIN, "pharmacie_detail")),
            "formulaire": render_to_string("pharmacies/ordonnance_form.html", {
                "form": OrdonnanceForm(), "ordonnance": None}, self.requete(MEDECIN, "ordonnance_creer")),
            "fiche pharmacie": render_to_string("pharmacies/pharmacie_form.html", {
                "form": PharmacieForm(instance=pharmacie, avec_compte=False), "pharmacie": pharmacie}, self.requete(PHARMACIE, "pharmacie_modifier")),
            "confirmation": render_to_string("pharmacies/ordonnance_supprimer.html", {"ordonnance": une_ordonnance()}, self.requete(MEDECIN)),
        }
        for nom, html in pages.items():
            with self.subTest(page=nom):
                self.assertEqual(verifier_html(html), [])

    def test_les_statuts_ont_leur_style(self):
        css = (RACINE / "pharmacies" / "static" / "pharmacies" / "pharmacies.css").read_text(encoding="utf-8")
        for statut in S.values:
            self.assertIn(f".st-{statut}", css, statut)


# --- Administration et commande de démonstration -------------------------------------------------------------


class AdministrationEtDemoTests(SimpleTestCase):
    def test_modeles_dans_l_administration(self):
        self.assertIn("statut", admin.site._registry[Ordonnance].list_filter)
        self.assertIn("ville", admin.site._registry[Pharmacie].list_filter)

    def test_la_demo_n_ecrit_aucun_mot_de_passe_dans_le_code(self):
        from .management.commands import charger_demo_pharmacies as demo

        source = inspect.getsource(demo)
        self.assertIn("secrets.token_urlsafe", source)
        self.assertNotIn('set_password("', source)
        self.assertNotEqual(demo.PREFIXE, "demo_")  # la démo des patients ne supprime pas celle-ci
        self.assertEqual(len({statut for statut, *_ in demo.ORDONNANCES}), 3)  # trois statuts différents


# --- Tableau de bord de la pharmacie -------------------------------------------------------------------------


from core.views import ConnexionView  # noqa: E402

from . import stats  # noqa: E402

MAINTENANT = timezone.now()


def une_ordonnance_recue(statut, il_y_a_jours=0, medicaments="Amoxicilline 1 g, 7 jours", patient_id=None, delivree_il_y_a=None):
    """Ordonnance en mémoire telle que la pharmacie la reçoit (dates posées à la main)."""
    o = une_ordonnance(statut=statut, medicaments=medicaments)
    o.modifie_le = MAINTENANT - datetime.timedelta(days=il_y_a_jours)
    o.delivree_le = MAINTENANT - datetime.timedelta(days=delivree_il_y_a) if delivree_il_y_a is not None else None
    if patient_id is not None:
        o.patient_id = patient_id
    return o


class StatistiquesPharmacieTests(SimpleTestCase):
    def ordonnances(self):
        p1, p2 = ObjectId(), ObjectId()
        return [
            une_ordonnance_recue(S.TRANSMISE, 2),
            une_ordonnance_recue(S.TRANSMISE, 0),
            une_ordonnance_recue(S.EN_PREPARATION, 1),
            une_ordonnance_recue(S.PRETE, 5),
            une_ordonnance_recue(S.PRETE, 1),
            une_ordonnance_recue(S.DELIVREE, patient_id=p1, delivree_il_y_a=0, medicaments="Paracétamol 1 g\nAmoxicilline 500 mg"),
            une_ordonnance_recue(S.DELIVREE, patient_id=p1, delivree_il_y_a=2),
            une_ordonnance_recue(S.DELIVREE, patient_id=p2, delivree_il_y_a=40),
            une_ordonnance_recue(S.ANNULEE, medicaments="Ibuprofène 400 mg"),
        ]

    def test_chiffres_cles(self):
        k = stats.chiffres_cles(self.ordonnances(), aujourdhui=timezone.localdate())
        self.assertEqual((k["a_preparer"], k["en_preparation"], k["pretes"]), (2, 1, 2))
        self.assertEqual(k["delivrees_aujourdhui"], 1)
        self.assertEqual(k["total"], 9)
        self.assertEqual(k["patients_servis"], 2)  # deux patients différents, même si l'un est venu deux fois
        self.assertEqual(k["taux_delivrance"], 75)  # 3 délivrées sur 4 terminées (1 annulée)

    def test_pas_de_division_par_zero(self):
        k = stats.chiffres_cles([])
        self.assertIsNone(k["taux_delivrance"])
        self.assertEqual(k["total"], 0)
        self.assertTrue(all(b["pourcentage"] == 0 for b in stats.repartition_par_statut([])))

    def test_repartition_relative_a_la_plus_grande_barre(self):
        barres = {b["cle"]: b for b in stats.repartition_par_statut(self.ordonnances())}
        self.assertEqual(barres[S.DELIVREE]["pourcentage"], 100)
        self.assertEqual(barres[S.EN_PREPARATION]["pourcentage"], 33)
        self.assertNotIn(S.EMISE, barres)  # une ordonnance émise n'a pas encore de pharmacie

    def test_sept_derniers_jours_du_plus_ancien_au_plus_recent(self):
        jours = stats.delivrees_par_jour(self.ordonnances(), aujourdhui=timezone.localdate())
        self.assertEqual(len(jours), 7)
        self.assertEqual(jours[-1]["cle"], timezone.localdate())
        self.assertEqual(jours[-1]["nombre"], 1)
        self.assertEqual(sum(j["nombre"] for j in jours), 2)  # celle d'il y a 40 jours est hors de la fenêtre

    def test_nom_du_medicament(self):
        self.assertEqual(stats.nom_du_medicament("amoxicilline 1 g, matin et soir"), "Amoxicilline")
        self.assertEqual(stats.nom_du_medicament("Sérum physiologique, lavage"), "Sérum physiologique")
        self.assertEqual(stats.nom_du_medicament("500 mg"), "")

    def test_medicaments_frequents_hors_ordonnances_annulees(self):
        frequents = {b["libelle"]: b["nombre"] for b in stats.medicaments_frequents(self.ordonnances())}
        self.assertEqual(frequents["Amoxicilline"], 8)
        self.assertEqual(frequents["Paracétamol"], 1)
        self.assertNotIn("Ibuprofène", frequents)

    def test_file_du_comptoir_la_plus_ancienne_d_abord(self):
        file = stats.a_traiter(self.ordonnances())
        self.assertEqual([o.statut for o in file], [S.TRANSMISE, S.EN_PREPARATION, S.TRANSMISE])
        self.assertTrue(all(a.modifie_le <= b.modifie_le for a, b in zip(file, file[1:])))

    def test_ordonnances_pretes_a_relancer(self):
        relances = stats.a_relancer(self.ordonnances(), maintenant=MAINTENANT)
        self.assertEqual(len(relances), 1)  # prête depuis 5 jours ; celle d'hier n'est pas encore à relancer


class ConnexionPharmacieTests(SimpleTestCase):
    def destination(self, **attributs):
        vue = ConnexionView()
        vue.request = RequestFactory().get("/comptes/connexion/")
        vue.request.user = un_user(**attributs)
        return vue.get_default_redirect_url()

    def test_une_pharmacie_arrive_sur_son_tableau_de_bord(self):
        self.assertEqual(self.destination(role="pharmacie"), "/pharmacies/tableau-de-bord/")
        self.assertEqual(self.destination(role="pharmacie", est_valide=False), "/pharmacies/tableau-de-bord/")

    def test_les_autres_roles_ne_changent_pas(self):
        self.assertEqual(self.destination(role="patient"), "/patients/tableau-de-bord/")
        self.assertEqual(self.destination(role="admin"), "/backoffice/")


class TableauDeBordVueTests(SimpleTestCase):
    def appeler(self, user, espace, fiche=None, ordonnances=()):
        requete = RequestFactory().get("/pharmacies/tableau-de-bord/")
        requete.user = user
        with mock.patch.object(views, "espace_de", return_value=espace), \
                mock.patch.object(views, "pharmacie_de", return_value=fiche), \
                mock.patch.object(Ordonnance.objects, "filter") as filtre, \
                mock.patch.object(views, "render") as rendre:
            filtre.return_value.select_related.return_value = list(ordonnances)
            views.tableau_de_bord(requete)
        return rendre.call_args.args[1], rendre.call_args.args[2], filtre

    def test_la_pharmacie_ne_voit_que_ses_ordonnances(self):
        fiche = une_pharmacie()
        gabarit, contexte, filtre = self.appeler(un_user(role="pharmacie"), PHARMACIE, fiche, [une_ordonnance_recue(S.TRANSMISE)])
        self.assertEqual(gabarit, "pharmacies/tableau_de_bord.html")
        filtre.assert_called_once_with(pharmacie=fiche)
        self.assertEqual(contexte["kpis"]["a_preparer"], 1)
        for cle in ("pharmacie", "a_traiter", "a_relancer", "repartition", "semaine", "frequents"):
            self.assertIn(cle, contexte)

    def test_compte_non_valide_ou_sans_fiche_explique_l_attente(self):
        gabarit, contexte, _ = self.appeler(un_user(role="pharmacie", est_valide=False), "")
        self.assertEqual(gabarit, "pharmacies/en_attente.html")
        self.assertFalse(contexte["sans_fiche"])
        _, contexte, _ = self.appeler(un_user(role="pharmacie"), "", fiche=None)
        self.assertTrue(contexte["sans_fiche"])

    def test_les_autres_comptes_sont_refuses(self):
        for role, espace in (("patient", PATIENT), ("medecin", MEDECIN)):
            with self.subTest(role=role), self.assertRaises(PermissionDenied):
                self.appeler(un_user(role=role), espace)

    def test_anonyme_renvoye_vers_la_connexion(self):
        reponse = self.client.get("/pharmacies/tableau-de-bord/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/?next=/pharmacies/tableau-de-bord/"))


class TableauDeBordPageTests(SimpleTestCase):
    def requete(self, espace):
        requete = RequestFactory().get("/pharmacies/tableau-de-bord/")
        requete.user = SimpleNamespace(is_authenticated=True, first_name="Hela", username="h", get_full_name=lambda: "Hela B")
        requete.espace = espace
        requete.resolver_match = SimpleNamespace(url_name="tableau_de_bord")
        return requete

    def rendre(self, ordonnances):
        fiche = une_pharmacie(de_garde=True, horaires="8 h – 20 h")
        fiche.cree_le = MAINTENANT
        return render_to_string("pharmacies/tableau_de_bord.html", {
            "pharmacie": fiche,
            "kpis": stats.chiffres_cles(ordonnances),
            "a_traiter": stats.a_traiter(ordonnances),
            "a_relancer": stats.a_relancer(ordonnances),
            "repartition": stats.repartition_par_statut(ordonnances),
            "semaine": stats.delivrees_par_jour(ordonnances),
            "frequents": stats.medicaments_frequents(ordonnances),
            "jours_relance": stats.JOURS_AVANT_RELANCE,
        }, self.requete(PHARMACIE))

    def test_informations_generales_et_chiffres(self):
        html = self.rendre([une_ordonnance_recue(S.TRANSMISE, 1), une_ordonnance_recue(S.PRETE, 6)])
        for texte in ("Pharmacie du Lac", "Informations générales", "8 h – 20 h", "À préparer", "Taux de délivrance",
                      "Délivrées sur 7 jours", "Médicaments les plus demandés", "Amoxicilline"):
            self.assertIn(texte, html)
        self.assertIn("Pensez à rappeler le patient", html)
        self.assertIn("?statut=transmise", html)  # chaque chiffre mène à la liste filtrée

    def test_le_menu_marque_le_tableau_de_bord(self):
        html = self.rendre([])
        self.assertIn("Rien à préparer pour le moment", html)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn("Tableau de bord</span>", html)

    def test_pages_du_tableau_de_bord_accessibles(self):
        self.assertEqual(verifier_html(self.rendre([une_ordonnance_recue(S.TRANSMISE), une_ordonnance_recue(S.PRETE, 6)])), [])
        attente = render_to_string("pharmacies/en_attente.html", {"sans_fiche": False}, self.requete(""))
        self.assertIn("En attente de validation", attente)
        self.assertEqual(verifier_html(attente), [])
