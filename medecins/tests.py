from datetime import datetime
from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .agenda import par_jour
from .annuaire import filtrer, trouver
from .forms import composer_prescription
from .horaires import analyser_jour
from .sms import envoyer_compte_rendu, lien_compte_rendu, message_compte_rendu, numero_sms
from patients.visio import config as config_jitsi, salle
from .models import Medecin, PlageHoraire, Prescription
from .views import tableau_de_bord

User = get_user_model()


class AnnuaireTests(SimpleTestCase):
    FICHES = [
        {"id": "m1", "nom": "Dr Sara Benali", "specialite": "Médecine générale", "ville": "Tunis"},
        {"id": "m2", "nom": "Dr Karim Trabelsi", "specialite": "Cardiologie", "ville": "Tunis"},
        {"id": "m3", "nom": "Dr Leïla Mansouri", "specialite": "Pédiatrie", "ville": "Sfax"},
    ]

    def test_filtrer_par_specialite_et_par_ville(self):
        self.assertEqual([m["id"] for m in filtrer("Cardiologie", "", self.FICHES)], ["m2"])
        self.assertTrue(all(m["ville"] == "Sfax" for m in filtrer("", "Sfax", self.FICHES)))

    def test_trouver_dans_une_liste_fournie(self):
        from unittest import mock
        with mock.patch("medecins.annuaire.tous", return_value=self.FICHES):
            self.assertEqual(trouver("m1")["nom"], "Dr Sara Benali")
            self.assertIsNone(trouver("inconnu"))


class HorairesTests(SimpleTestCase):
    def test_une_journee_type(self):
        self.assertEqual(analyser_jour("9-12, 14-17"), [(9, 12), (14, 17)])

    def test_texte_vide(self):
        self.assertEqual(analyser_jour("  "), [])

    def test_plage_illisible(self):
        with self.assertRaises(ValueError):
            analyser_jour("matin")

    def test_plage_inversee(self):
        with self.assertRaises(ValueError):
            analyser_jour("17-9")

    def test_chevauchement(self):
        with self.assertRaises(ValueError):
            analyser_jour("9-13, 12-16")


class MedecinPlanningTests(SimpleTestCase):
    def test_planning_et_nom(self):
        medecin = Medecin(specialite="Cardiologie", ville="Tunis", disponible=True)
        medecin.user = User(first_name="Sara", last_name="Benali", username="m1")
        medecin.plages = [
            PlageHoraire(jour=0, debut=14, fin=17),
            PlageHoraire(jour=0, debut=9, fin=12),
        ]
        medecin.code = "m1"
        self.assertEqual(medecin.nom_affiche, "Dr Sara Benali")
        self.assertEqual(medecin.horaires_planning(), {0: [(9, 12), (14, 17)]})
        self.assertEqual(
            medecin.vers_fiche(),
            {"id": "m1", "nom": "Dr Sara Benali", "specialite": "Cardiologie", "ville": "Tunis", "disponible": True, "horaires": {0: [(9, 12), (14, 17)]}},
        )

    def test_medecin_absent_sans_creneau(self):
        medecin = Medecin(disponible=False)
        medecin.plages = [PlageHoraire(jour=0, debut=9, fin=12)]
        self.assertEqual(medecin.horaires_planning(), {})


class SmsCompteRenduTests(SimpleTestCase):
    def consultation(self, telephone="20 111 222"):
        class Patient:
            def __str__(self):
                return "Amel Trabelsi"

        patient = Patient()
        patient.telephone = telephone
        return SimpleNamespace(
            pk="c1",
            patient=patient,
            date=timezone.make_aware(datetime(2026, 10, 26, 14, 30)),
            medecin_nom="Dr Sara Benali",
            medecin_specialite="Médecine générale",
            motif="Toux",
            resume="Toux depuis trois jours.",
            diagnostic="Bronchite",
            prescription="Paracétamol 1 g, 3 fois par jour",
            recommandations="Repos",
        )

    def test_un_numero_tunisien_recoit_l_indicatif(self):
        self.assertEqual(numero_sms("20 111 222"), "21620111222")
        self.assertEqual(numero_sms("+216 96 084 471"), "21696084471")
        self.assertEqual(numero_sms("0021620111222"), "21620111222")

    @override_settings(SMS_NUMERO_TEST="")
    def test_un_numero_inutilisable_n_ouvre_pas_de_sms(self):
        self.assertIsNone(numero_sms(""))
        self.assertIsNone(numero_sms("123"))
        self.assertIsNone(lien_compte_rendu(self.consultation("")))

    @override_settings(SMS_NUMERO_TEST="")
    def test_le_lien_contient_le_compte_rendu_et_le_numero_du_patient(self):
        lien = lien_compte_rendu(self.consultation())
        self.assertTrue(lien.startswith("sms:+21620111222?&body="))
        texte = message_compte_rendu(self.consultation())
        self.assertIn("Amel Trabelsi", texte)
        self.assertIn("Toux depuis trois jours.", texte)
        self.assertIn("Paracétamol 1 g, 3 fois par jour", texte)
        self.assertIn("Dr Sara Benali (Médecine générale)", texte)

    @override_settings(
        SMS_NUMERO_TEST="+21652241079",
        TWILIO_FROM="+21696084471",
        TWILIO_ACCOUNT_SID="",
        TWILIO_AUTH_TOKEN="",
        TWILIO_API_KEY_SID="",
        TWILIO_API_KEY_SECRET="",
        TWILIO_MESSAGING_SERVICE_SID="",
    )
    def test_lessai_part_du_medecin_et_arrive_au_patient(self):
        lien = lien_compte_rendu(self.consultation("20111222"))
        self.assertTrue(lien.startswith("sms:+21652241079?&body="))
        self.assertIn(quote_attendu("+216 52 241 079"), lien)
        self.assertIn(quote_attendu("+216 96 084 471"), lien)
        self.assertIn(quote_attendu("Amel Trabelsi"), lien)
        resultat = envoyer_compte_rendu(self.consultation("20111222"))
        self.assertEqual(resultat["mode"], "lien")
        self.assertEqual(resultat["numero"], "21652241079")

    @override_settings(
        SMS_MODE="twilio",
        SMS_NUMERO_TEST="+21652241079",
        TWILIO_ACCOUNT_SID="ACxxx",
        TWILIO_AUTH_TOKEN="jeton",
        TWILIO_API_KEY_SID="SKxxx",
        TWILIO_API_KEY_SECRET="secret-cle",
        TWILIO_MESSAGING_SERVICE_SID="MGxxx",
        TWILIO_FROM="+21696084471",
    )
    def test_avec_twilio_le_clic_envoie_le_sms(self):
        from unittest import mock
        from urllib.parse import parse_qs
        reponse = mock.Mock()
        reponse.read.return_value = b"{}"
        reponse.__enter__ = mock.Mock(return_value=reponse)
        reponse.__exit__ = mock.Mock(return_value=False)
        with mock.patch("medecins.sms.urllib.request.urlopen", return_value=reponse) as ouvrir:
            resultat = envoyer_compte_rendu(self.consultation("20111222"))
        self.assertEqual(resultat["mode"], "api")
        self.assertEqual(resultat["numero"], "21652241079")
        requete = ouvrir.call_args.args[0]
        corps = parse_qs(requete.data.decode())
        self.assertEqual(corps["To"], ["+21652241079"])
        self.assertEqual(corps["From"], ["+21696084471"])
        self.assertEqual(corps["MessagingServiceSid"], ["MGxxx"])
        self.assertIn("Toux depuis trois jours.", corps["Body"][0])
        self.assertIn("+216 52 241 079", corps["Body"][0])
        self.assertIn("+216 96 084 471", corps["Body"][0])
        import base64
        self.assertEqual(
            requete.get_header("Authorization"),
            "Basic " + base64.b64encode(b"ACxxx:jeton").decode(),
        )

    def test_le_bouton_poste_vers_lenvoi(self):
        html = render_to_string("medecins/_sms.html", {
            "sms": True,
            "essai": True,
            "telephone": "+216 52 241 079",
            "expediteur": "+216 96 084 471",
            "consultation": SimpleNamespace(pk="c1"),
        }, request=RequestFactory().get("/"))
        self.assertIn("Envoyer au patient par SMS", html)
        self.assertIn("/medecins/consultations/c1/sms/", html)
        self.assertIn("+216 52 241 079", html)
        self.assertIn("+216 96 084 471", html)
        self.assertIn('method="post"', html)

    def test_sans_numero_le_medecin_est_prevenu(self):
        html = render_to_string("medecins/_sms.html", {"sms": False, "telephone": "", "essai": False})
        self.assertNotIn("/sms/", html)
        self.assertIn("n'a pas de numéro", html)


def quote_attendu(morceau):
    from urllib.parse import quote
    return quote(morceau)


class WhatsAppCompteRenduTests(SimpleTestCase):
    def consultation(self, telephone="20111222"):
        return SmsCompteRenduTests.consultation(self, telephone)

    @override_settings(WHATSAPP_TOKEN="", WHATSAPP_PHONE_ID="", SMS_NUMERO_TEST="+21652241079")
    def test_sans_jeton_lenvoi_est_refuse(self):
        from .whatsapp import EchecEnvoi, envoyer_compte_rendu as envoyer
        with self.assertRaises(EchecEnvoi):
            envoyer(self.consultation())

    @override_settings(
        WHATSAPP_TOKEN="EAAtest",
        WHATSAPP_PHONE_ID="1398895369978434",
        WHATSAPP_VERSION="v25.0",
        WHATSAPP_FROM="+15551491710",
        WHATSAPP_PIN="584217",
        SMS_NUMERO_TEST="+21652241079",
        TWILIO_FROM="+21696084471",
    )
    def test_le_clic_envoie_le_compte_rendu(self):
        import json
        from unittest import mock
        from .whatsapp import envoyer_compte_rendu as envoyer
        reponse = mock.Mock()
        reponse.read.return_value = b"{}"
        reponse.__enter__ = mock.Mock(return_value=reponse)
        reponse.__exit__ = mock.Mock(return_value=False)
        with mock.patch("medecins.whatsapp.urllib.request.urlopen", return_value=reponse) as ouvrir:
            resultat = envoyer(self.consultation("20111222"))
        self.assertEqual(resultat["mode"], "api")
        self.assertEqual(resultat["numero"], "21620111222")
        requete = ouvrir.call_args.args[0]
        self.assertEqual(
            requete.full_url,
            "https://graph.facebook.com/v25.0/1398895369978434/messages",
        )
        self.assertEqual(requete.get_header("Authorization"), "Bearer EAAtest")
        corps = json.loads(requete.data.decode())
        self.assertEqual(corps["to"], "21620111222")
        self.assertEqual(corps["type"], "text")
        self.assertIn("Toux depuis trois jours.", corps["text"]["body"])
        self.assertIn("+216 20 111 222", corps["text"]["body"])
        self.assertNotIn("52241079", corps["text"]["body"])

    @override_settings(
        WHATSAPP_TOKEN="EAAtest",
        WHATSAPP_PHONE_ID="1398895369978434",
        WHATSAPP_VERSION="v25.0",
        WHATSAPP_PIN="584217",
        SMS_NUMERO_TEST="+21652241079",
    )
    def test_un_numero_non_enregistre_est_enregistre_puis_renvoye(self):
        import json
        from io import BytesIO
        from unittest import mock
        from urllib.error import HTTPError
        from .whatsapp import envoyer_compte_rendu as envoyer
        charge = json.dumps({"error": {"code": 133010, "message": "Account not registered"}}).encode()
        refus = HTTPError("https://graph.facebook.com", 400, "Bad Request", hdrs=None, fp=BytesIO(charge))
        ok = mock.Mock()
        ok.read.return_value = b"{}"
        ok.__enter__ = mock.Mock(return_value=ok)
        ok.__exit__ = mock.Mock(return_value=False)
        with mock.patch("medecins.whatsapp.urllib.request.urlopen", side_effect=[refus, ok, ok]) as ouvrir:
            resultat = envoyer(self.consultation("20111222"))
        self.assertEqual(resultat["numero"], "21620111222")
        adresses = [appel.args[0].full_url for appel in ouvrir.call_args_list]
        self.assertTrue(adresses[1].endswith("/register"))
        self.assertTrue(adresses[2].endswith("/messages"))

    @override_settings(
        WHATSAPP_TOKEN="EAAtest",
        WHATSAPP_PHONE_ID="1398895369978434",
        WHATSAPP_VERSION="v25.0",
        SMS_NUMERO_TEST="+21652241079",
    )
    def test_le_lancement_notifie_le_telephone_du_patient(self):
        import json
        from unittest import mock
        from .whatsapp import notifier_lancement
        triage = SimpleNamespace(pk="abc123", patient=SimpleNamespace(telephone="52241079"))
        reponse = mock.Mock()
        reponse.read.return_value = b"{}"
        reponse.__enter__ = mock.Mock(return_value=reponse)
        reponse.__exit__ = mock.Mock(return_value=False)
        with mock.patch("medecins.whatsapp.urllib.request.urlopen", return_value=reponse) as ouvrir:
            resultat = notifier_lancement(triage, "Dr Sara Benali")
        self.assertEqual(resultat["numero"], "21652241079")
        corps = json.loads(ouvrir.call_args.args[0].data.decode())
        self.assertEqual(corps["to"], "21652241079")
        self.assertIn("Dr Sara Benali a lancé votre consultation.", corps["text"]["body"])
        self.assertIn("https://meet.guifi.net/mediconnect-abc123", corps["text"]["body"])
        triage.patient.telephone = "96084471"
        with mock.patch("medecins.whatsapp.urllib.request.urlopen", return_value=reponse):
            autre = notifier_lancement(triage, "Dr Sara Benali")
        self.assertEqual(autre["numero"], "21696084471")

    def test_le_bouton_affiche_le_numero_du_patient(self):
        from .whatsapp import contexte_envoi
        contexte = contexte_envoi(self.consultation("52241079"))
        self.assertEqual(contexte["telephone"], "+216 52 241 079")
        contexte = contexte_envoi(self.consultation("96084471"))
        self.assertEqual(contexte["telephone"], "+216 96 084 471")
        self.assertNotEqual(contexte["telephone"], "+216 52 241 079")

    def test_le_bouton_poste_vers_whatsapp(self):
        html = render_to_string("medecins/_whatsapp.html", {
            "whatsapp": True,
            "telephone": "+216 20 111 222",
            "expediteur": "+15551491710",
            "consultation": SimpleNamespace(pk="c1"),
        }, request=RequestFactory().get("/"))
        self.assertIn("Envoyer au patient par WhatsApp", html)
        self.assertIn("/medecins/consultations/c1/whatsapp/", html)
        self.assertIn("+216 20 111 222", html)
        self.assertIn('method="post"', html)

    def test_un_jeton_expire_est_explique(self):
        import json
        from io import BytesIO
        from urllib.error import HTTPError
        from .whatsapp import _message_refus
        charge = json.dumps({"error": {"code": 190, "message": "Error validating access token"}}).encode()
        erreur = HTTPError("https://graph.facebook.com", 401, "Unauthorized", hdrs=None, fp=BytesIO(charge))
        self.assertIn("expiré", _message_refus(erreur))


class CourrielCompteRenduTests(SimpleTestCase):
    def consultation(self, email="amel@exemple.tn"):
        class Patient:
            def __str__(self):
                return "Amel Trabelsi"

        patient = Patient()
        patient.user = SimpleNamespace(email=email)
        return SimpleNamespace(
            pk="c1",
            patient=patient,
            date=timezone.make_aware(datetime(2026, 10, 26, 14, 30)),
            medecin_nom="Dr Sara Benali",
            medecin_specialite="Médecine générale",
            motif="Toux",
            resume="Toux depuis trois jours.",
            diagnostic="Bronchite",
            prescription="Paracétamol",
            recommandations="Repos",
            actes=None,
        )

    def test_le_pdf_contient_le_compte_rendu(self):
        from .courriel import pdf_compte_rendu
        pdf = pdf_compte_rendu(self.consultation())
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 500)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        EMAIL_HOST_USER="medecin@exemple.tn",
        EMAIL_HOST_PASSWORD="mot-de-passe-application",
        DEFAULT_FROM_EMAIL="MediConnect <medecin@exemple.tn>",
    )
    def test_le_pdf_part_vers_lemail_du_patient(self):
        from django.core import mail
        from .courriel import envoyer_compte_rendu as envoyer
        resultat = envoyer(self.consultation("patient.un@exemple.tn"))
        self.assertEqual(resultat["email"], "patient.un@exemple.tn")
        self.assertEqual(mail.outbox[0].to, ["patient.un@exemple.tn"])
        nom, contenu, mime = mail.outbox[0].attachments[0]
        self.assertTrue(nom.endswith(".pdf"))
        self.assertEqual(mime, "application/pdf")
        self.assertTrue(contenu.startswith(b"%PDF"))
        autre = envoyer(self.consultation("patient.deux@exemple.tn"))
        self.assertEqual(autre["email"], "patient.deux@exemple.tn")
        self.assertEqual(mail.outbox[1].to, ["patient.deux@exemple.tn"])

    def test_sans_adresse_lenvoi_est_refuse(self):
        from .courriel import EchecEnvoi, envoyer_compte_rendu as envoyer
        with self.assertRaises(EchecEnvoi):
            envoyer(self.consultation(""))

    def test_le_bouton_affiche_ladresse_du_patient(self):
        html = render_to_string("medecins/_courriel.html", {
            "courriel": True,
            "email": "patient.un@exemple.tn",
            "consultation": SimpleNamespace(pk="c1"),
        }, request=RequestFactory().get("/"))
        self.assertIn("Envoyer le PDF par e-mail", html)
        self.assertIn("/medecins/consultations/c1/courriel/", html)
        self.assertIn("patient.un@exemple.tn", html)
        self.assertIn('method="post"', html)


class PrescriptionTexteTests(SimpleTestCase):
    def test_seuls_les_actes_remplis_apparaissent(self):
        texte = composer_prescription("Paracétamol 1 g, 3 fois par jour", "", "Pansement quotidien")
        self.assertIn("Ordonnance\nParacétamol 1 g, 3 fois par jour", texte)
        self.assertNotIn("Examens", texte)
        self.assertIn("Soins à domicile\nPansement quotidien", texte)

    def test_rien_a_prescrire(self):
        self.assertEqual(composer_prescription("", "  ", None), "")


class EspaceMedecinAccesTests(SimpleTestCase):
    def test_les_adresses_du_module(self):
        self.assertEqual(reverse("medecins:tableau_de_bord"), "/medecins/")
        self.assertEqual(reverse("medecins:inscription"), "/medecins/inscription/")
        self.assertEqual(reverse("medecins:consultations"), "/medecins/consultations/")
        self.assertEqual(reverse("medecins:envoyer_sms", args=["abc"]), "/medecins/consultations/abc/sms/")
        self.assertEqual(reverse("medecins:envoyer_whatsapp", args=["abc"]), "/medecins/consultations/abc/whatsapp/")
        self.assertEqual(reverse("medecins:envoyer_courriel", args=["abc"]), "/medecins/consultations/abc/courriel/")
        self.assertEqual(reverse("medecins:synthese", args=["abc"]), "/medecins/file/abc/")

    def test_un_visiteur_est_renvoye_vers_la_connexion(self):
        reponse = self.client.get("/medecins/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/?next=/medecins/"))

    def test_un_patient_ne_voit_pas_la_file(self):
        requete = RequestFactory().get("/medecins/")
        requete.user = User(username="patient", role="patient", is_active=True, est_valide=True)
        with self.assertRaises(PermissionDenied):
            tableau_de_bord(requete)

    def test_la_page_d_inscription_s_affiche(self):
        reponse = self.client.get("/medecins/inscription/")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Créer un compte médecin")

    def test_les_modeles_sont_dans_l_admin(self):
        self.assertTrue(admin.site.is_registered(Medecin))
        self.assertTrue(admin.site.is_registered(Prescription))


class AgendaTests(SimpleTestCase):
    def test_les_patients_deja_en_file_sont_classes_par_heure(self):
        tz = timezone.get_current_timezone()
        matin = timezone.make_aware(datetime(2026, 10, 26, 9, 0), tz)
        apres_midi = timezone.make_aware(datetime(2026, 10, 26, 14, 30), tz)
        lendemain = timezone.make_aware(datetime(2026, 10, 27, 8, 0), tz)
        file = [SimpleNamespace(prise_en_charge_estimee=apres_midi, cree_le=matin, creneau=None)]
        file[0].patient = "Hichem"
        planning = [
            SimpleNamespace(creneau=lendemain, patient="Nour"),
            SimpleNamespace(creneau=matin, patient="Amira"),
        ]
        jours = par_jour(file, planning)
        self.assertEqual([e["demande"].patient for e in jours[0]["evenements"]], ["Amira", "Hichem"])
        self.assertEqual(jours[0]["evenements"][0]["fixe"], True)
        self.assertEqual(jours[0]["evenements"][1]["fixe"], False)
        self.assertEqual(jours[1]["jour"].isoformat(), "2026-10-27")
        self.assertEqual(jours[1]["evenements"][0]["demande"].patient, "Nour")

    def test_sans_heure_estimee_on_reprend_l_heure_de_la_demande(self):
        tz = timezone.get_current_timezone()
        cree = timezone.make_aware(datetime(2026, 10, 26, 11, 15), tz)
        demande = SimpleNamespace(prise_en_charge_estimee=None, cree_le=cree, creneau=None, patient="Sami")
        jours = par_jour([demande], [])
        self.assertEqual(jours[0]["evenements"][0]["heure"].hour, 11)
        self.assertEqual(jours[0]["evenements"][0]["heure"].minute, 15)


class VisioPartageeTests(SimpleTestCase):
    def test_medecin_et_patient_entrent_dans_la_meme_salle(self):
        demande = SimpleNamespace(pk="abc123")
        medecin = config_jitsi(demande, "Dr MOURAD MISSAOUI")
        patient = config_jitsi(demande, "Smail Chemlali")
        self.assertEqual(salle(demande), "mediconnect-abc123")
        self.assertEqual(medecin["salle"], patient["salle"])
        self.assertEqual(medecin["lien"], patient["lien"])
        self.assertEqual(medecin["lien"], "https://meet.guifi.net/mediconnect-abc123")
        self.assertEqual(medecin["nom"], "Dr MOURAD MISSAOUI")
        self.assertEqual(patient["nom"], "Smail Chemlali")

