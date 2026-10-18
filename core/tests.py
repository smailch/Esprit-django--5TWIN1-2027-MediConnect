from pathlib import Path

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase
from django.urls import NoReverseMatch, resolve, reverse

from .views import ConnexionView

User = get_user_model()


class AuthentificationDansCoreTests(SimpleTestCase):
    def test_urls_de_connexion_et_deconnexion(self):
        self.assertEqual(reverse("core:connexion"), "/comptes/connexion/")
        self.assertEqual(reverse("core:deconnexion"), "/comptes/deconnexion/")
        self.assertIs(resolve("/comptes/connexion/").func.view_class, ConnexionView)

    def test_l_authentification_n_est_plus_dans_patients(self):
        for nom in ("patients:connexion", "patients:deconnexion"):
            with self.assertRaises(NoReverseMatch):
                reverse(nom)

    def test_page_de_connexion_s_affiche(self):
        reponse = self.client.get("/comptes/connexion/")
        self.assertEqual(reponse.status_code, 200)
        self.assertTemplateUsed(reponse, "core/connexion.html")
        self.assertTemplateUsed(reponse, "core/layout.html")
        self.assertContains(reponse, "Se connecter")

    def test_acces_protege_renvoie_vers_la_connexion_de_core(self):
        reponse = self.client.get("/patients/profil/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(
            reponse["Location"].startswith("/comptes/connexion/?next=/patients/profil/")
        )

    def test_deconnexion_refuse_le_get(self):
        self.assertEqual(self.client.get("/comptes/deconnexion/").status_code, 405)

    def test_inscription_patient_reste_dans_patients(self):
        reponse = self.client.get("/patients/inscription/")
        self.assertEqual(reponse.status_code, 200)
        self.assertTemplateUsed(reponse, "patients/inscription.html")
        self.assertTemplateUsed(reponse, "patients/layout.html")
        self.assertTemplateUsed(reponse, "core/layout.html")


class RedirectionApresConnexionTests(SimpleTestCase):
    def destination(self, **attributs):
        requete = RequestFactory().get("/comptes/connexion/")
        requete.user = User(**attributs)  # non enregistré : aucun accès base
        vue = ConnexionView()
        vue.request = requete
        return vue.get_default_redirect_url()

    def test_patient_vers_son_tableau_de_bord(self):
        self.assertEqual(self.destination(role="patient"), "/patients/tableau-de-bord/")

    def test_personnel_vers_l_admin(self):
        self.assertEqual(self.destination(role="admin", is_staff=True), "/admin/")

    def test_autres_roles_vers_l_accueil(self):
        self.assertEqual(self.destination(role="medecin"), "/")


class AdminUserTests(SimpleTestCase):
    def setUp(self):
        self.model_admin = admin.site._registry.get(User)

    def test_user_est_enregistre_dans_l_admin(self):
        self.assertTrue(admin.site.is_registered(User))

    def test_les_formulaires_visent_core_user(self):
        self.assertIs(self.model_admin.form._meta.model, User)
        self.assertIs(self.model_admin.add_form._meta.model, User)

    def test_role_et_validation_sont_modifiables(self):
        champs = [
            champ
            for _, options in self.model_admin.get_fieldsets(None, None)
            for champ in options["fields"]
        ]
        self.assertIn("role", champs)
        self.assertIn("est_valide", champs)

    def test_actions_de_validation(self):
        self.assertEqual(
            sorted(self.model_admin.actions), ["retirer_validation", "valider_comptes"]
        )

    def test_filtres_et_colonnes(self):
        self.assertIn("role", self.model_admin.list_filter)
        self.assertIn("est_valide", self.model_admin.list_display)


class GabaritsParAppTests(SimpleTestCase):
    PROJET = ["base.html", "home.html"]
    CORE = ["core/layout.html", "core/connexion.html", "core/_champ.html"]
    PATIENTS = [
        "patients/layout.html",
        "patients/inscription.html",
        "patients/profil.html",
        "patients/medecins.html",
        "patients/symptomes.html",
        "patients/resultat.html",
        "patients/tableau_de_bord.html",
        "patients/file_medecin.html",
        "patients/_propositions.html",
    ]

    def test_tous_les_gabarits_sont_trouves(self):
        for nom in self.PROJET + self.CORE + self.PATIENTS:
            with self.subTest(gabarit=nom):
                get_template(nom)

    def test_l_ancien_cadre_a_disparu(self):
        with self.assertRaises(TemplateDoesNotExist):
            get_template("auth_base.html")

    def test_chaque_gabarit_est_dans_le_dossier_de_son_app(self):
        attendu = {"core": self.CORE, "patients": self.PATIENTS}
        for app, noms in attendu.items():
            for nom in noms:
                chemin = Path(get_template(nom).origin.name).as_posix()
                with self.subTest(gabarit=nom):
                    self.assertIn(f"/{app}/templates/{nom}", chemin)

    def test_gabarits_du_projet_au_niveau_projet(self):
        for nom in self.PROJET:
            chemin = Path(get_template(nom).origin.name).as_posix()
            with self.subTest(gabarit=nom):
                self.assertIn(f"/templates/{nom}", chemin)
                self.assertNotIn("/core/templates/", chemin)
                self.assertNotIn("/patients/templates/", chemin)


class MiseEnPageLargeTests(SimpleTestCase):
    """Les pages utilisent toute la largeur sur ordinateur (colonnes) et une seule
    colonne sur mobile ; seules les cartes de compte restent étroites."""

    PAGES_PATIENT = [
        "symptomes", "medecins", "tableau_de_bord", "profil", "resultat", "file_medecin",
    ]

    def source(self, nom):
        return Path(get_template(nom).origin.name).read_text(encoding="utf-8")

    def test_les_pages_patient_ne_sont_pas_enfermees_dans_une_colonne_etroite(self):
        import re

        for page in self.PAGES_PATIENT:
            with self.subTest(page=page):
                src = self.source(f"patients/{page}.html")
                self.assertIsNone(
                    re.search(r"block largeur %\}max-w-(xs|sm|md|lg|xl|2xl|3xl)", src), page
                )

    def test_le_cadre_commun_est_large_par_defaut(self):
        src = self.source("core/layout.html")
        self.assertIn("max-w-7xl", src)
        self.assertIn("{% block largeur %}{% endblock %}", src)  # aucune largeur imposée

    def test_les_pages_ont_des_colonnes_sur_grand_ecran(self):
        attendu = {
            "symptomes": "lg:grid-cols-12",
            "tableau_de_bord": "lg:grid-cols-12",
            "resultat": "lg:grid-cols-12",
            "medecins": "lg:grid-cols-3",
            "profil": "lg:grid-cols-2",
        }
        for page, classe in attendu.items():
            with self.subTest(page=page):
                self.assertIn(classe, self.source(f"patients/{page}.html"))

    def test_la_connexion_garde_une_carte_etroite(self):
        self.assertIn("max-w-md", self.source("core/connexion.html"))

    def test_la_page_des_symptomes_range_les_blocs_dans_un_ordre_logique_sur_mobile(self):
        src = self.source("patients/symptomes.html")
        # Ordre visuel sur mobile : symptômes (1), échelles (2), température (3),
        # description (4), envoi (5). Chaque rang doit désigner le bon bloc.
        for n, repere in ((1, "titre-symptomes"), (2, "titre-echelles"), (3, "form.temperature"), (4, "form.texte_libre")):
            bloc = src[src.index(f"order-{n}"):]
            self.assertIn(repere, bloc[:700], f"order-{n}")
        self.assertIn("order-5", src)

    def test_fond_bleu_fonce_et_cartes_bleu_pale(self):
        css = (Path(__file__).resolve().parent.parent / "static" / "css" / "ui.css").read_text(encoding="utf-8")
        self.assertIn("#0A2540", css)  # bleu nuit du dégradé de fond
        self.assertIn(".page-bg .glass", css)
        self.assertIn("rgba(238, 246, 255", css)  # carte bleu très pâle, pas blanc pur

    def test_l_en_tete_peut_passer_a_la_ligne_sur_mobile(self):
        self.assertIn("flex-wrap", self.source("core/layout.html"))
