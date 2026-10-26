"""Tests d'intégration de core : vraie base (MongoDB de test) et client HTTP de Django.

Connexion et blocage après échecs, journal des accès, rôles -> groupes et permissions Django, contrôle d'accès de
TOUS les espaces par URL directe, gestion des comptes par l'administrateur, protection CSRF, pages d'erreur et
réglages de sécurité.

Lancement : python manage.py test   (MongoDB local requis, voir MONGODB_TEST_URI dans settings.py)
"""
import os
import subprocess
import sys

from django.conf import settings
from django.contrib.auth.models import Group
from django.core import mail
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import Client, TestCase, override_settings

from core import fabriques_test as f
from core.models import JournalConnexion, User
from infirmiers.models import InterventionDomicile

E = JournalConnexion.Evenement


class ConnexionTests(TestCase):
    def setUp(self):
        cache.clear()  # compteurs d'échecs
        self.patient = f.un_patient("amel")

    def connecter(self, mot_de_passe, identifiant="amel", **extra):
        return self.client.post("/comptes/connexion/", {"username": identifiant, "password": mot_de_passe}, **extra)

    def test_connexion_reussie_journalisee_et_redirigee_vers_son_espace(self):
        reponse = self.connecter(f.MOT_DE_PASSE, REMOTE_ADDR="10.0.0.7", HTTP_USER_AGENT="Firefox")
        self.assertRedirects(reponse, "/patients/tableau-de-bord/")
        entree = JournalConnexion.objects.get()
        self.assertEqual((entree.evenement, entree.utilisateur, entree.adresse_ip, entree.navigateur),
                         (E.CONNEXION, self.patient.user, "10.0.0.7", "Firefox"))

    def test_echec_journalise_sans_le_mot_de_passe(self):
        reponse = self.connecter("mauvais-mot-de-passe")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "mot de passe valides")
        entree = JournalConnexion.objects.get()
        self.assertEqual((entree.evenement, entree.identifiant, entree.utilisateur), (E.ECHEC, "amel", None))
        self.assertNotIn("mauvais", str(JournalConnexion.objects.values().get()))

    def test_blocage_apres_cinq_echecs_meme_avec_le_bon_mot_de_passe(self):
        for _ in range(settings.CONNEXION_ESSAIS_MAX):
            self.connecter("faux")
        self.assertEqual(JournalConnexion.objects.filter(evenement=E.BLOCAGE).count(), 1)
        reponse = self.connecter(f.MOT_DE_PASSE)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Trop de tentatives de connexion")
        self.assertNotIn("_auth_user_id", self.client.session)
        # un autre compte n'est pas bloqué
        f.un_patient("sami")
        self.assertRedirects(self.connecter(f.MOT_DE_PASSE, identifiant="sami"), "/patients/tableau-de-bord/")

    def test_une_connexion_reussie_remet_le_compteur_a_zero(self):
        for _ in range(settings.CONNEXION_ESSAIS_MAX - 1):
            self.connecter("faux")
        self.assertRedirects(self.connecter(f.MOT_DE_PASSE), "/patients/tableau-de-bord/")
        self.client.logout()
        for _ in range(settings.CONNEXION_ESSAIS_MAX - 1):
            self.connecter("faux")
        self.assertRedirects(self.connecter(f.MOT_DE_PASSE), "/patients/tableau-de-bord/")

    def test_compte_desactive_refuse(self):
        self.patient.user.is_active = False
        self.patient.user.save()
        self.assertEqual(self.connecter(f.MOT_DE_PASSE).status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deconnexion_en_post_seulement_et_journalisee(self):
        self.client.force_login(self.patient.user)
        self.assertEqual(self.client.get("/comptes/deconnexion/").status_code, 405)
        self.assertRedirects(self.client.post("/comptes/deconnexion/"), "/", fetch_redirect_response=False)
        self.assertTrue(JournalConnexion.objects.filter(evenement=E.DECONNEXION, utilisateur=self.patient.user).exists())

    def test_mot_de_passe_hache(self):
        user = self.patient.user
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertNotIn(f.MOT_DE_PASSE, user.password)
        self.assertTrue(user.check_password(f.MOT_DE_PASSE))


class RolesEtPermissionsTests(TestCase):
    def test_chaque_compte_dans_le_groupe_de_son_role(self):
        attendus = {
            f.un_patient().user: "Patients", f.un_medecin().user: "Médecins", f.un_infirmier().user: "Infirmiers",
            f.une_pharmacie().user: "Pharmacies", f.un_admin(): "Administrateurs",
        }
        for user, groupe in attendus.items():
            with self.subTest(role=user.role):
                self.assertEqual(list(user.groups.values_list("name", flat=True)), [groupe])

    def test_changer_de_role_change_de_groupe_et_de_permissions(self):
        user = f.un_infirmier().user
        self.assertTrue(user.has_perm("infirmiers.change_interventiondomicile"))
        self.assertFalse(user.has_perm("core.change_user"))
        user.role = User.Role.ADMIN
        user.save()
        user = User.objects.get(pk=user.pk)  # permissions relues (cache de l'objet)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Administrateurs"])
        self.assertTrue(user.has_perm("core.change_user"))

    def test_les_groupes_ont_leurs_permissions(self):
        admins = Group.objects.get(name="Administrateurs")
        codes = set(admins.permissions.values_list("codename", flat=True))
        self.assertTrue({"view_user", "change_user", "view_journalconnexion"} <= codes)
        self.assertFalse(Group.objects.get(name="Patients").permissions.filter(codename="change_user").exists())


class ControleAccesParUrlTests(TestCase):
    """Chaque espace est réservé à son rôle, même en tapant l'adresse : anonyme -> connexion, autre rôle -> 403."""

    ESPACES = {
        User.Role.PATIENT: ["/patients/tableau-de-bord/", "/patients/dossier/", "/patients/allergies/", "/patients/mesures/", "/infirmiers/soins/"],
        User.Role.MEDECIN: ["/medecins/", "/medecins/consultations/", "/medecins/profil/"],
        User.Role.INFIRMIER: ["/infirmiers/tableau-de-bord/", "/infirmiers/demandes/", "/infirmiers/planning/", "/infirmiers/profil/"],
        User.Role.PHARMACIE: ["/pharmacies/tableau-de-bord/", "/pharmacies/stock/", "/pharmacies/ma-pharmacie/"],
        User.Role.ADMIN: ["/backoffice/", "/backoffice/patients/", "/backoffice/comptes/", "/backoffice/comptes/journal/",
                          "/infirmiers/alertes/", "/backoffice/pharmacies/"],
    }

    def test_matrice_des_acces(self):
        comptes = {
            User.Role.PATIENT: f.un_patient().user, User.Role.MEDECIN: f.un_medecin().user,
            User.Role.INFIRMIER: f.un_infirmier().user, User.Role.PHARMACIE: f.une_pharmacie().user,
            User.Role.ADMIN: f.un_admin(),
        }
        for proprietaire, urls in self.ESPACES.items():
            for url in urls:
                self.client.logout()
                with self.subTest(url=url, visiteur="anonyme"):
                    reponse = self.client.get(url)
                    self.assertEqual(reponse.status_code, 302)
                    self.assertTrue(reponse["Location"].startswith("/comptes/connexion/?next="))
                for role, user in comptes.items():
                    self.client.force_login(user)
                    with self.subTest(url=url, visiteur=role):
                        self.assertEqual(self.client.get(url).status_code, 200 if role == proprietaire else 403)

    def test_la_page_403_est_personnalisee(self):
        self.client.force_login(f.un_patient().user)
        reponse = self.client.get("/backoffice/")
        self.assertEqual(reponse.status_code, 403)
        self.assertTemplateUsed(reponse, "403.html")
        self.assertContains(reponse, "Cette page ne vous est pas accessible", status_code=403)

    def test_l_objet_d_un_autre_patient_est_introuvable(self):
        from patients.models import Allergie

        autre = f.un_patient()
        allergie = Allergie.objects.create(patient=autre, substance="Pénicilline")
        self.client.force_login(f.un_patient().user)
        self.assertEqual(self.client.get(f"/patients/allergies/{allergie.pk}/modifier/").status_code, 404)
        self.assertEqual(self.client.post(f"/patients/allergies/{allergie.pk}/supprimer/").status_code, 404)
        self.assertTrue(Allergie.objects.filter(pk=allergie.pk).exists())


class GestionDesComptesTests(TestCase):
    def setUp(self):
        self.admin = f.un_admin("chef")
        self.client.force_login(self.admin)

    def action(self, compte, action, **donnees):
        return self.client.post(f"/backoffice/comptes/{compte.pk}/{action}/", donnees)

    def test_liste_filtres_et_chiffres(self):
        f.un_patient("amel")
        en_attente = f.un_infirmier("ines", est_valide=False).user
        reponse = self.client.get("/backoffice/comptes/")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "amel")
        self.assertEqual(reponse.context["chiffres"]["a_valider"], 1)
        reponse = self.client.get("/backoffice/comptes/", {"statut": "a_valider"})
        self.assertEqual([c.pk for c in reponse.context["comptes"]], [en_attente.pk])
        reponse = self.client.get("/backoffice/comptes/", {"role": "patient", "q": "ame"})
        self.assertEqual([c.username for c in reponse.context["comptes"]], ["amel"])

    def test_valider_puis_retirer_un_infirmier(self):
        user = f.un_infirmier("ines", est_valide=False).user
        self.assertRedirects(self.action(user, "valider"), "/backoffice/comptes/")
        user.refresh_from_db()
        self.assertTrue(user.est_valide)
        self.action(user, "retirer")
        user.refresh_from_db()
        self.assertFalse(user.est_valide)

    def test_un_patient_n_a_pas_de_validation(self):
        user = f.un_patient().user
        reponse = self.action(user, "retirer")
        self.assertRedirects(reponse, "/backoffice/comptes/")
        user.refresh_from_db()
        self.assertTrue(user.est_valide)

    def test_desactiver_un_infirmier_rend_ses_passages_et_previent_les_patients(self):
        infirmier = f.un_infirmier("sami")
        patient = f.un_patient()
        intervention = InterventionDomicile.objects.create(
            patient=patient, type_soin="injection", adresse="7 rue de Rome", ville="Tunis",
            date_souhaitee=f.demain().date(), moment="matin",
        )
        intervention.accepter(infirmier, f.demain(9))
        intervention.save()
        mail.outbox = []
        self.action(infirmier.user, "desactiver")
        infirmier.user.refresh_from_db()
        intervention.refresh_from_db()
        self.assertFalse(infirmier.user.is_active)
        self.assertEqual((intervention.statut, intervention.infirmier_id), (InterventionDomicile.Statut.DEMANDEE, None))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [patient.user.email])
        self.action(infirmier.user, "reactiver")
        infirmier.user.refresh_from_db()
        self.assertTrue(infirmier.user.is_active)

    def test_pas_sur_son_propre_compte_ni_sur_le_personnel(self):
        self.action(self.admin, "desactiver")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        staff = f.un_admin(is_staff=True)
        self.action(staff, "desactiver")
        staff.refresh_from_db()
        self.assertTrue(staff.is_active)

    def test_retour_seulement_vers_ce_site(self):
        user = f.un_patient().user
        reponse = self.action(user, "desactiver", next="https://pirate.example/")
        self.assertRedirects(reponse, "/backoffice/comptes/")
        reponse = self.action(user, "reactiver", next="/backoffice/comptes/?role=patient")
        self.assertRedirects(reponse, "/backoffice/comptes/?role=patient")

    def test_actions_en_post_et_reservees_a_la_permission(self):
        user = f.un_patient().user
        self.assertEqual(self.client.get(f"/backoffice/comptes/{user.pk}/desactiver/").status_code, 405)
        self.client.force_login(f.un_infirmier().user)
        self.assertEqual(self.action(user, "desactiver").status_code, 403)
        self.client.logout()
        self.assertEqual(self.action(user, "desactiver").status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_journal_des_connexions(self):
        Client().post("/comptes/connexion/", {"username": "inconnu", "password": "x"})
        reponse = self.client.get("/backoffice/comptes/journal/", {"evenement": "echec"})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual([e.identifiant for e in reponse.context["entrees"]], ["inconnu"])


class CsrfTests(TestCase):
    def test_formulaire_sans_jeton_refuse_avec_une_page_claire(self):
        client = Client(enforce_csrf_checks=True)
        reponse = client.post("/comptes/connexion/", {"username": "x", "password": "y"})
        self.assertEqual(reponse.status_code, 403)
        self.assertTemplateUsed(reponse, "403_csrf.html")

    def test_formulaire_avec_jeton_accepte(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/comptes/connexion/")
        jeton = client.cookies["csrftoken"].value
        reponse = client.post("/comptes/connexion/", {"username": "x", "password": "y", "csrfmiddlewaretoken": jeton})
        self.assertEqual(reponse.status_code, 200)


class PagesErreurEtSanteTests(TestCase):
    def test_404_personnalisee(self):
        reponse = self.client.get("/cette-page-n-existe-pas/")
        self.assertEqual(reponse.status_code, 404)
        self.assertTemplateUsed(reponse, "404.html")
        self.assertContains(reponse, "Cette page n'existe pas", status_code=404)

    def test_identifiant_mal_forme_404_et_pas_500(self):
        self.client.force_login(f.un_patient().user)
        self.assertEqual(self.client.get("/patients/allergies/pas-un-id/modifier/").status_code, 404)

    def test_500_affichable_sans_contexte(self):
        html = render_to_string("500.html")
        self.assertIn("Un problème est survenu", html)
        self.assertIn('lang="fr"', html)

    @override_settings(DEBUG_PROPAGATE_EXCEPTIONS=False)
    def test_une_exception_donne_la_page_500(self):
        from unittest import mock

        client = Client(raise_request_exception=False)
        with mock.patch("django.views.generic.base.TemplateView.get", side_effect=RuntimeError("panne")), \
                self.assertLogs("django.request", level="ERROR"):
            reponse = client.get("/")
        self.assertEqual(reponse.status_code, 500)
        self.assertContains(reponse, "Un problème est survenu", status_code=500)

    def test_sonde_de_sante(self):
        reponse = self.client.get("/sante/")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json(), {"application": "ok", "base": "ok"})


class ReglagesDeSecuriteTests(TestCase):
    def test_en_tetes_de_securite(self):
        reponse = self.client.get("/comptes/connexion/")
        self.assertEqual(reponse["X-Frame-Options"], "DENY")
        self.assertEqual(reponse["X-Content-Type-Options"], "nosniff")
        self.assertEqual(reponse["Referrer-Policy"], "same-origin")

    def test_cookie_de_session_inaccessible_au_javascript(self):
        self.client.post("/comptes/connexion/", {"username": f.un_patient("lina").user.username, "password": f.MOT_DE_PASSE})
        self.assertTrue(self.client.cookies[settings.SESSION_COOKIE_NAME]["httponly"])

    def _demarrer(self, **env):
        """Charge les réglages dans un processus séparé avec ces variables d'environnement (prioritaires sur .env)."""
        variables = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "MONGODB_TEST"))}
        variables.update(env)
        code = "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='mediconnect.settings'; django.setup(); from django.conf import settings; print(settings.DEBUG, settings.SESSION_COOKIE_SECURE, settings.SECURE_SSL_REDIRECT)"
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=variables, cwd=settings.BASE_DIR)

    def test_la_production_refuse_debug_et_la_cle_d_exemple(self):
        sortie = self._demarrer(DJANGO_ENV="production", DJANGO_DEBUG="True", DJANGO_SECRET_KEY="x" * 50)
        self.assertIn("DJANGO_DEBUG doit valoir False", sortie.stderr)
        sortie = self._demarrer(DJANGO_ENV="production", DJANGO_DEBUG="False", DJANGO_SECRET_KEY="change-me")
        self.assertIn("DJANGO_SECRET_KEY", sortie.stderr)

    def test_la_production_active_https_et_cookies_securises(self):
        sortie = self._demarrer(DJANGO_ENV="production", DJANGO_DEBUG="False", DJANGO_SECRET_KEY="k" * 50)
        self.assertEqual(sortie.stdout.split(), ["False", "True", "True"], sortie.stderr)

    def test_secrets_lus_dans_l_environnement_jamais_ecrits_dans_le_code(self):
        import re

        reglages = (settings.BASE_DIR / "mediconnect" / "settings.py").read_text(encoding="utf-8")
        # toute variable sensible vient de os.environ, jamais d'une valeur écrite en dur
        self.assertEqual(re.findall(r"^\w*(?:SECRET|PASSWORD|TOKEN|API_KEY|CLE_API)\w* = ['\"]", reglages, re.M), [])
        self.assertNotIn("gsk_", reglages)  # préfixe des clés Groq
        ignores = (settings.BASE_DIR / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn(".env", ignores)
