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
        self.assertTemplateUsed(reponse, "core/auth_layout.html")
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
        self.assertTemplateUsed(reponse, "core/auth_layout.html")


class RedirectionApresConnexionTests(SimpleTestCase):
    def destination(self, **attributs):
        requete = RequestFactory().get("/comptes/connexion/")
        requete.user = User(**attributs)  # non enregistré : aucun accès base
        vue = ConnexionView()
        vue.request = requete
        return vue.get_default_redirect_url()

    def test_patient_vers_son_tableau_de_bord(self):
        self.assertEqual(self.destination(role="patient"), "/patients/tableau-de-bord/")

    def test_personnel_vers_l_espace_administrateur(self):
        self.assertEqual(self.destination(role="admin", is_staff=True), "/backoffice/")
        self.assertEqual(self.destination(role="admin"), "/backoffice/")
        self.assertEqual(self.destination(is_superuser=True), "/backoffice/")

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
    CORE = [
        "core/layout.html",
        "core/auth_layout.html",
        "core/connexion.html",
        "core/_champ.html",
        "core/_head_app.html",
    ]
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
        "patients/_etapes.html",
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

    def test_le_cadre_commun_est_une_application_avec_menu_lateral(self):
        src = self.source("core/layout.html")
        for repere in ("app-shell", 'class="rail"', "rail-nav", "topbar", "{% block nav %}", "{% block page %}"):
            self.assertIn(repere, src, repere)
        self.assertNotIn("block largeur", src)  # plus aucune largeur imposée

    def test_les_pages_ont_des_colonnes_sur_grand_ecran(self):
        attendu = {
            "symptomes": "lg:grid-cols-12",
            "tableau_de_bord": "lg:grid-cols-12",
            "resultat": "lg:grid-cols-12",
            "medecins": "lg:grid-cols-3",
            "profil": "lg:grid-cols-12",
        }
        for page, classe in attendu.items():
            with self.subTest(page=page):
                self.assertIn(classe, self.source(f"patients/{page}.html"))

    def test_connexion_et_inscription_sont_en_ecran_partage(self):
        self.assertIn("auth-brand", self.source("core/auth_layout.html"))
        self.assertIn("auth-pane", self.source("core/auth_layout.html"))
        for gabarit in ("core/connexion.html", "patients/inscription.html"):
            self.assertIn('extends "core/auth_layout.html"', self.source(gabarit), gabarit)

    def test_la_page_des_symptomes_range_les_blocs_dans_un_ordre_logique_sur_mobile(self):
        src = self.source("patients/symptomes.html")
        # Ordre visuel sur mobile : symptômes (1), échelles (2), température (3),
        # description (4), envoi (5). Chaque rang doit désigner le bon bloc.
        for n, repere in ((1, "titre-symptomes"), (2, "titre-echelles"), (3, "form.temperature"), (4, "form.texte_libre")):
            bloc = src[src.index(f"order-{n}"):]
            self.assertIn(repere, bloc[:700], f"order-{n}")
        self.assertIn("order-5", src)

    def css(self):
        return (Path(__file__).resolve().parent.parent / "static" / "css" / "ui.css").read_text(encoding="utf-8")

    def app_css(self):
        return (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")

    def regle(self, selecteur):
        """Corps de la règle CSS dont le sélecteur est exactement `selecteur`."""
        import re

        m = re.search(r"(?m)^" + re.escape(selecteur) + r"\s*\{(.*?)\n?\}", self.css(), re.S)
        self.assertIsNotNone(m, f"règle {selecteur} introuvable")
        return m.group(1)

    def test_theme_sombre_bleu_nuit(self):
        css = self.css()
        self.assertIn("color-scheme: dark", css)
        self.assertIn("#050E1C", css)  # bleu nuit du fond
        self.assertIn("rgba(20, 44, 80", css)  # verre bleu foncé des cartes

    def test_plus_de_voile_blanc_sur_la_video_de_l_accueil(self):
        for selecteur in (".hero-veil", ".hero-video", ".hero-tint"):
            corps = self.regle(selecteur)
            self.assertNotIn("255, 255, 255", corps, selecteur)
            self.assertNotIn("#fff", corps.lower(), selecteur)
        self.assertNotIn("brightness(1.3", self.css())  # l'ancien éclaircissement a disparu
        self.assertNotIn("mix-blend-mode: screen", self.css())  # ni la fusion « écran »

    def test_plus_de_trait_blanc_sur_les_boutons_et_les_cartes(self):
        css = self.css()
        self.assertNotIn(".btn::before", css)  # reflet blanc supprimé
        self.assertNotIn(".btn::after", css)  # liseré intérieur supprimé
        self.assertNotIn("inset 0 1px 0", css)  # filet clair en haut des panneaux
        for selecteur in (".glass", ".btn-glass", ".btn-primary", ".btn-light", ".chip", ".field", ".choice"):
            corps = self.regle(selecteur)
            for ligne in corps.splitlines():
                if "border" in ligne:
                    self.assertNotIn("255, 255, 255", ligne, f"{selecteur} : {ligne.strip()}")
                    self.assertNotIn("#fff", ligne.lower(), f"{selecteur} : {ligne.strip()}")

    def test_la_palette_des_gabarits_est_sombre(self):
        base = self.source("base.html")
        self.assertIn("bg-[#050E1C]", base)
        self.assertNotIn("bg-white antialiased", base)
        self.assertIn("accent: '#67E8F9'", base)
        # texte courant clair : gray-800 est la couleur de texte principale
        self.assertIn("800: '#E3ECF7'", base)

    def test_plus_de_fond_blanc_dans_les_gabarits(self):
        import re

        racine = Path(__file__).resolve().parent.parent
        for chemin in list(racine.glob("templates/**/*.html")) + list(racine.glob("*/templates/**/*.html")):
            src = chemin.read_text(encoding="utf-8")
            with self.subTest(gabarit=chemin.name):
                self.assertIsNone(re.search(r"bg-white(?!/(?:[1-9]|10)(?![0-9]))", src), chemin.name)

    def test_la_navigation_devient_une_barre_d_onglets_sur_mobile(self):
        css = self.app_css()
        # Par défaut (mobile) : barre fixée en bas ; à partir de 1024 px : colonne latérale.
        mobile = css[: css.index("@media (min-width: 1024px)")]
        self.assertRegex(mobile, r"\.rail \{[^}]*position: fixed;[^}]*bottom: 0")
        self.assertIn(".topbar", mobile)
        large = css[css.index("@media (min-width: 1024px)"):]
        self.assertIn("grid-template-columns: 17rem", large)
        self.assertRegex(large, r"\.topbar \{ display: none; \}")


class StyleEspacePatientTests(SimpleTestCase):
    """app.css : surfaces pleines, boutons plats, échelle d'urgence en motif signature."""

    def setUp(self):
        self.css = (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")

    def regle(self, selecteur):
        import re

        m = re.search(r"(?m)^" + re.escape(selecteur) + r"\s*\{(.*?)\n?\}", self.css, re.S)
        self.assertIsNotNone(m, f"règle {selecteur} introuvable")
        return m.group(1)

    def test_aucun_flou_d_arriere_plan_donc_plus_rapide(self):
        # `backdrop-filter: none` (remise à zéro des champs) est permis, un flou ne l'est pas.
        import re

        for ligne in self.css.splitlines():
            if "backdrop-filter" in ligne:
                self.assertRegex(ligne, r"backdrop-filter:\s*none", ligne)
        self.assertNotRegex(self.css, r"blur\(")

    def test_les_boutons_sont_plats_sans_reflet_ni_trait_blanc(self):
        for selecteur in (".abtn", ".abtn-primary", ".abtn-outline", ".abtn-ghost", ".abtn-danger"):
            corps = self.regle(selecteur)
            self.assertNotIn("gradient", corps, selecteur)
            self.assertNotIn("255, 255, 255", corps, selecteur)
            self.assertNotIn("box-shadow", corps, selecteur)
        self.assertNotIn(".abtn::before", self.css)
        self.assertNotIn(".abtn::after", self.css)
        self.assertIn("border-radius: 0.75rem", self.regle(".abtn"))  # angles arrondis, plus de pilule
        self.assertNotIn("9999px", self.regle(".abtn"))

    def test_boutons_assez_grands_pour_le_tactile(self):
        self.assertIn("min-height: 44px", self.regle(".abtn"))
        self.assertIn("min-height: 44px", self.regle(".chip-select"))

    def test_texte_du_bouton_principal_tres_contraste(self):
        def luminance(h):
            h = h.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

        def contraste(a, b):
            la, lb = sorted((luminance(a), luminance(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)

        self.assertGreaterEqual(contraste("#2DD4BF", "#04181A"), 7)   # bouton principal
        self.assertGreaterEqual(contraste("#E6EEF8", "#0C1A30"), 7)   # texte sur surface
        self.assertGreaterEqual(contraste("#8FA6C4", "#0C1A30"), 4.5)  # texte secondaire
        for niveau in ("#F87171", "#FB923C", "#FACC15", "#4ADE80", "#7DD3FC"):
            self.assertGreaterEqual(contraste("#0B1220", niveau), 4.5, niveau)  # pastilles d'urgence

    def test_les_couleurs_du_css_sont_bien_celles_testees(self):
        for jeton in ("--a-accent: #2DD4BF", "--a-accent-ink: #04181A", "--a-text: #E6EEF8", "--a-muted: #8FA6C4",
                      "--u1: #F87171", "--u2: #FB923C", "--u3: #FACC15", "--u4: #4ADE80", "--u5: #7DD3FC"):
            self.assertIn(jeton, self.css)

    def test_les_six_valeurs_des_echelles_ont_chacune_une_couleur(self):
        for valeur in range(6):
            self.assertIn(f".sc-{valeur} {{ --sc: ", self.css, f"échelle {valeur}")

    def test_les_champs_natifs_sont_masques_mais_restent_accessibles(self):
        from patients.forms import SymptomesForm

        champ = SymptomesForm.base_fields["symptomes"]
        self.assertEqual(champ.widget.attrs.get("class"), "sr-only")  # lisible au clavier, invisible
        for nom in ("douleur", "fievre", "respiration", "etat_general"):
            self.assertEqual(SymptomesForm.base_fields[nom].widget.attrs.get("class"), "sr-only", nom)

    def test_focus_visible_au_clavier(self):
        self.assertIn(".chip-select:has(:focus-visible)", self.css)
        self.assertIn(".scale-opt:has(:focus-visible)", self.css)
        self.assertIn(".app a:focus-visible", self.css)

    def test_l_accueil_n_utilise_pas_ce_style(self):
        racine = Path(__file__).resolve().parent.parent
        home = (racine / "templates" / "home.html").read_text(encoding="utf-8")
        self.assertNotIn("abtn", home)
        self.assertNotIn("app.css", home)
        base = (racine / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertNotIn("app.css", base)  # chargé seulement par les pages intérieures
        self.assertIn("{% block head %}", base)


class EtapesEtGabaritsTests(SimpleTestCase):
    def rendre(self, nom, **contexte):
        from django.template.loader import render_to_string

        return render_to_string(nom, contexte)

    def test_la_barre_d_etapes_marque_l_etape_en_cours(self):
        html = self.rendre("patients/_etapes.html", etape=2)
        self.assertEqual(html.count('aria-current="step"'), 1)
        self.assertIn("step-done", html)  # l'étape 1 est faite
        self.assertIn("step-current", html)
        self.assertIn("Médecin", html)
        self.assertIn("Symptômes", html)
        self.assertIn("Résultat", html)

    def test_etape_1_aucune_etape_terminee(self):
        self.assertNotIn("step-done", self.rendre("patients/_etapes.html", etape=1))

    def test_etape_3_les_deux_premieres_sont_terminees(self):
        html = self.rendre("patients/_etapes.html", etape=3)
        self.assertEqual(html.count("step-done"), 2)
        self.assertEqual(html.count('aria-current="step"'), 1)

    def test_champ_de_formulaire_avec_libelle_aide_et_erreur(self):
        from django import forms

        class F(forms.Form):
            nom = forms.CharField(label="Votre nom", help_text="Au moins 2 lettres.")

        f = F(data={"nom": ""})
        f.is_valid()
        html = self.rendre("core/_champ.html", field=f["nom"])
        self.assertIn('class="f-label"', html)
        self.assertIn("Votre nom", html)
        self.assertIn("Au moins 2 lettres.", html)
        self.assertIn('role="alert"', html)  # l'erreur est annoncée aux lecteurs d'écran
        self.assertIn('aria-hidden="true"', html)  # l'astérisque n'est pas lue

    def test_le_cadre_n_affiche_pas_le_bouton_de_deconnexion_a_un_visiteur(self):
        reponse = self.client.get("/comptes/connexion/")
        self.assertNotContains(reponse, "Se déconnecter")
        self.assertContains(reponse, "Les cas graves passent d")  # présentation de l'écran partagé
        for libelle in ("Vital", "Très urgent", "Urgent", "Standard", "Non urgent"):
            self.assertContains(reponse, libelle)


class IdentifiantMalFormeTests(SimpleTestCase):
    """Un identifiant d'adresse invalide doit donner « introuvable » (404), jamais une erreur serveur (500)."""

    def test_l_utilitaire_repond_404_pour_un_identifiant_invalide(self):
        from django.http import Http404

        from core.utils import objet_ou_404
        from patients.models import Triage

        for mauvais in ("pas-un-id", "123", "", "zzzzzzzzzzzzzzzzzzzzzzzz"):
            with self.subTest(identifiant=mauvais):
                with self.assertRaises(Http404):
                    objet_ou_404(Triage, pk=mauvais)

    def test_les_vues_utilisent_l_utilitaire_et_plus_get_object_or_404(self):
        racine = Path(__file__).resolve().parent.parent
        for chemin in ("patients/views.py", "backoffice/views.py"):
            src = (racine / chemin).read_text(encoding="utf-8")
            with self.subTest(fichier=chemin):
                self.assertIn("objet_ou_404", src)
                self.assertNotIn("get_object_or_404(", src)
