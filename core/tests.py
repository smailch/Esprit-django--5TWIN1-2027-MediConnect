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

    def test_medecin_vers_son_espace(self):
        self.assertEqual(self.destination(role="medecin"), "/medecins/")

    def test_autres_roles_vers_l_accueil(self):
        self.assertEqual(self.destination(role="infirmier"), "/")
        self.assertEqual(self.destination(role="pharmacie"), "/")
        self.assertEqual(self.destination(role="laboratoire"), "/")


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


# --- Mot de passe : changement, oubli, e-mail unique ----------------------------------------------------------
import re  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

from bson import ObjectId  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.forms import PasswordResetForm  # noqa: E402
from django.core import mail  # noqa: E402
from django.test import override_settings  # noqa: E402

from . import views  # noqa: E402
from .forms import ChangementMotDePasseForm, DemandeReinitialisationForm, NouveauMotDePasseForm, email_deja_utilise  # noqa: E402

ANCIEN, NOUVEAU = "Ancien-Mdp-2026!", "Nouveau-Mdp-2027?"
SESSIONS_EN_COOKIE = "django.contrib.sessions.backends.signed_cookies"  # aucune base de données pour les sessions
HACHAGE_RAPIDE = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])  # les vrais hachages sont lents


def un_compte(**kw):
    valeurs = dict(pk=ObjectId(), username="amel", first_name="Amel", last_name="Zouari", email="amel@exemple.tn")
    valeurs.update(kw)
    compte = User(**valeurs)
    compte.set_password(ANCIEN)
    return compte


class AdressesMotDePasseTests(SimpleTestCase):
    def test_adresses(self):
        attendu = {
            "mot_de_passe": "/comptes/mot-de-passe/",
            "reinitialisation": "/comptes/mot-de-passe-oublie/",
            "reinitialisation_envoyee": "/comptes/mot-de-passe-oublie/envoye/",
            "reinitialisation_terminee": "/comptes/reinitialisation/terminee/",
        }
        for nom, adresse in attendu.items():
            with self.subTest(nom=nom):
                self.assertEqual(reverse(f"core:{nom}"), adresse)
        self.assertEqual(reverse("core:reinitialisation_confirmation", kwargs={"uidb64": "abc", "token": "set-password"}), "/comptes/reinitialisation/abc/set-password/")

    def test_vues(self):
        self.assertIs(resolve("/comptes/mot-de-passe/").func.view_class, views.ChangementMotDePasseView)
        self.assertIs(resolve("/comptes/mot-de-passe-oublie/").func.view_class, views.ReinitialisationView)
        self.assertIs(resolve("/comptes/reinitialisation/terminee/").func.view_class, views.ReinitialisationTermineeView)
        self.assertIs(resolve("/comptes/reinitialisation/abc/def/").func.view_class, views.ReinitialisationConfirmationView)

    def test_changer_son_mot_de_passe_demande_d_etre_connecte(self):
        reponse = self.client.get("/comptes/mot-de-passe/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))

    def test_la_connexion_propose_mot_de_passe_oublie(self):
        reponse = self.client.get("/comptes/connexion/")
        self.assertContains(reponse, "Mot de passe oublié ?")
        self.assertContains(reponse, 'href="/comptes/mot-de-passe-oublie/"')

    def test_pages_publiques(self):
        for adresse, gabarit, texte in (
            ("/comptes/mot-de-passe-oublie/", "core/reinitialisation.html", "Envoyer le lien"),
            ("/comptes/mot-de-passe-oublie/envoye/", "core/reinitialisation_envoyee.html", "Vérifiez votre messagerie"),
            ("/comptes/reinitialisation/terminee/", "core/reinitialisation_terminee.html", "Mot de passe changé"),
        ):
            with self.subTest(adresse=adresse):
                reponse = self.client.get(adresse)
                self.assertEqual(reponse.status_code, 200)
                self.assertTemplateUsed(reponse, gabarit)
                self.assertTemplateUsed(reponse, "core/auth_layout.html")
                self.assertContains(reponse, texte)

    def test_un_lien_invalide_est_explique(self):
        reponse = self.client.get("/comptes/reinitialisation/zzz/lien-bidon/")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Ce lien n'est plus valable")
        self.assertContains(reponse, 'href="/comptes/mot-de-passe-oublie/"')

    def test_le_lien_dure_deux_heures_et_le_courriel_est_configurable(self):
        self.assertEqual(settings.PASSWORD_RESET_TIMEOUT, 2 * 60 * 60)
        exemple = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
        for variable in ("EMAIL_BACKEND", "EMAIL_HOST", "EMAIL_HOST_USER", "DEFAULT_FROM_EMAIL"):
            self.assertIn(variable, exemple)
        self.assertNotRegex(exemple, r"EMAIL_HOST_PASSWORD=\S")  # le modèle ne contient aucun secret


class EmailUniqueTests(SimpleTestCase):
    def test_la_recherche_ignore_les_majuscules_et_les_espaces(self):
        with mock.patch.object(User.objects, "filter") as filtre:
            filtre.return_value.exists.return_value = True
            self.assertTrue(email_deja_utilise("  Amel@Exemple.TN "))
        filtre.assert_called_once_with(email__iexact="Amel@Exemple.TN")

    def test_on_peut_exclure_son_propre_compte(self):
        pk = ObjectId()
        with mock.patch.object(User.objects, "filter") as filtre:
            filtre.return_value.exclude.return_value.exists.return_value = False
            self.assertFalse(email_deja_utilise("a@b.tn", exclure_pk=pk))
        filtre.return_value.exclude.assert_called_once_with(pk=pk)


@HACHAGE_RAPIDE
class FormulairesMotDePasseTests(SimpleTestCase):
    def donnees(self, **kw):
        valeurs = {"old_password": ANCIEN, "new_password1": NOUVEAU, "new_password2": NOUVEAU}
        valeurs.update(kw)
        return valeurs

    def test_changement_valide(self):
        compte = un_compte()
        form = ChangementMotDePasseForm(compte, self.donnees())
        self.assertTrue(form.is_valid(), form.errors)
        form.save(commit=False)
        self.assertTrue(compte.check_password(NOUVEAU))

    def test_ancien_mot_de_passe_faux(self):
        form = ChangementMotDePasseForm(un_compte(), self.donnees(old_password="faux"))
        self.assertFalse(form.is_valid())
        self.assertIn("old_password", form.errors)

    def test_confirmation_differente(self):
        form = ChangementMotDePasseForm(un_compte(), self.donnees(new_password2="autre-chose-123"))
        self.assertFalse(form.is_valid())
        self.assertIn("new_password2", form.errors)

    def test_mot_de_passe_trop_faible_refuse(self):
        for faible in ("12345678", "azerty", "password"):
            with self.subTest(faible=faible):
                form = ChangementMotDePasseForm(un_compte(), self.donnees(new_password1=faible, new_password2=faible))
                self.assertFalse(form.is_valid())
                self.assertIn("new_password2", form.errors)

    def test_libelles_en_francais_et_style_commun(self):
        form = ChangementMotDePasseForm(un_compte())
        self.assertEqual(
            [c.label for c in form.fields.values()], ["Mot de passe actuel", "Nouveau mot de passe", "Confirmation du nouveau mot de passe"]
        )
        self.assertTrue(all(c.widget.attrs.get("class") == "field" for c in form.fields.values()))
        self.assertEqual(DemandeReinitialisationForm().fields["email"].label, "Adresse e-mail de votre compte")
        self.assertEqual(NouveauMotDePasseForm(un_compte()).fields["new_password1"].label, "Nouveau mot de passe")

    def test_nouveau_mot_de_passe_apres_oubli(self):
        compte = un_compte()
        form = NouveauMotDePasseForm(compte, {"new_password1": NOUVEAU, "new_password2": NOUVEAU})
        self.assertTrue(form.is_valid(), form.errors)
        form.save(commit=False)
        self.assertTrue(compte.check_password(NOUVEAU))
        self.assertFalse(compte.check_password(ANCIEN))


@HACHAGE_RAPIDE
class ChangementMotDePasseVueTests(SimpleTestCase):
    def vue(self, utilisateur):
        requete = RequestFactory().get("/comptes/mot-de-passe/")
        requete.user = utilisateur
        vue = views.ChangementMotDePasseView()
        vue.setup(requete)
        return vue

    def test_un_patient_garde_son_menu_et_revient_a_son_compte(self):
        contexte = self.vue(SimpleNamespace(is_authenticated=True, patient=object())).get_context_data()
        self.assertEqual((contexte["cadre"], contexte["retour"]), ("patients/layout.html", "/patients/compte/"))

    def test_les_autres_roles_ont_le_cadre_commun(self):
        contexte = self.vue(SimpleNamespace(is_authenticated=True)).get_context_data()
        self.assertEqual((contexte["cadre"], contexte["retour"]), ("core/layout.html", "/"))

    def test_apres_le_changement_un_message_et_la_session_reste_ouverte(self):
        compte = un_compte()
        vue = self.vue(compte)
        form = ChangementMotDePasseForm(compte, {"old_password": ANCIEN, "new_password1": NOUVEAU, "new_password2": NOUVEAU})
        self.assertTrue(form.is_valid())
        with mock.patch.object(User, "save"), mock.patch("django.contrib.auth.views.update_session_auth_hash") as garde_session, \
                mock.patch.object(views, "messages") as messages:
            reponse = vue.form_valid(form)
        garde_session.assert_called_once()  # sans cela, changer son mot de passe déconnecterait le patient
        messages.success.assert_called_once()
        self.assertEqual((reponse.status_code, reponse["Location"]), (302, "/comptes/mot-de-passe/"))
        self.assertTrue(compte.check_password(NOUVEAU))


@HACHAGE_RAPIDE
@override_settings(SESSION_ENGINE=SESSIONS_EN_COOKIE)
class ReinitialisationParcoursTests(SimpleTestCase):
    """Le parcours complet « mot de passe oublié », avec un faux compte (aucune base de données)."""

    def setUp(self):
        self.compte = un_compte()

    def demander(self, email, comptes):
        with mock.patch.object(PasswordResetForm, "get_users", return_value=comptes):
            return self.client.post("/comptes/mot-de-passe-oublie/", {"email": email})

    def lien(self):
        return re.search(r"http://testserver(/comptes/reinitialisation/\S+)", mail.outbox[0].body).group(1)

    def test_un_message_part_avec_un_lien(self):
        reponse = self.demander("amel@exemple.tn", [self.compte])
        self.assertRedirects(reponse, "/comptes/mot-de-passe-oublie/envoye/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["amel@exemple.tn"])
        self.assertEqual(message.subject, "Réinitialisation de votre mot de passe MediConnect")  # une seule ligne
        for texte in ("Bonjour Amel Zouari", "identifiant : amel", "valable deux heures", "ignorez ce message"):
            self.assertIn(texte, message.body)
        self.assertNotIn("&#x27;", message.body)  # texte brut : pas d'échappement HTML

    def test_meme_reponse_pour_une_adresse_inconnue(self):
        reponse = self.demander("inconnu@exemple.tn", [])
        self.assertRedirects(reponse, "/comptes/mot-de-passe-oublie/envoye/", fetch_redirect_response=False)
        self.assertEqual(mail.outbox, [])  # on ne révèle pas qui a un compte

    def test_adresse_mal_formee(self):
        reponse = self.client.post("/comptes/mot-de-passe-oublie/", {"email": "pas-une-adresse"})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("email", reponse.context["form"].errors)
        self.assertEqual(mail.outbox, [])

    def test_le_lien_permet_de_choisir_un_nouveau_mot_de_passe_une_seule_fois(self):
        self.demander("amel@exemple.tn", [self.compte])
        lien = self.lien()
        with mock.patch.object(type(User._default_manager), "get", return_value=self.compte), mock.patch.object(User, "save"):
            etape = self.client.get(lien)  # le jeton passe en session, puis on est redirigé vers le formulaire
            self.assertEqual(etape.status_code, 302)
            formulaire = self.client.get(etape["Location"])
            self.assertEqual(formulaire.status_code, 200)
            self.assertContains(formulaire, "Enregistrer le mot de passe")
            fin = self.client.post(etape["Location"], {"new_password1": NOUVEAU, "new_password2": NOUVEAU})
            self.assertRedirects(fin, "/comptes/reinitialisation/terminee/", fetch_redirect_response=False)
            self.assertTrue(self.compte.check_password(NOUVEAU))
            reutilise = self.client.get(lien)  # le lien est lié à l'ancien mot de passe : il ne sert plus
            self.assertContains(reutilise, "Ce lien n'est plus valable")

    def test_mot_de_passe_trop_faible_refuse_apres_oubli(self):
        self.demander("amel@exemple.tn", [self.compte])
        with mock.patch.object(type(User._default_manager), "get", return_value=self.compte), mock.patch.object(User, "save"):
            etape = self.client.get(self.lien())
            reponse = self.client.post(etape["Location"], {"new_password1": "12345678", "new_password2": "12345678"})
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(self.compte.check_password(ANCIEN))  # rien n'a changé


# --- Accessibilité --------------------------------------------------------------------------------------------------
import io  # noqa: E402

from django import forms as django_forms  # noqa: E402
from django.contrib.auth.models import AnonymousUser  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.template import engines  # noqa: E402
from django.template.loader import render_to_string  # noqa: E402

from .accessibilite import SEUIL_TEXTE_NORMAL, contraste, contrastes_du_projet, couleurs_css, verifier_html  # noqa: E402
from .forms import ConnexionForm, StyledFormMixin  # noqa: E402

RACINE_PROJET = Path(__file__).resolve().parent.parent
PAGE_PARFAITE = (
    "<!doctype html><html lang='fr'><head><title>Une page</title></head><body><a href='#c'>Aller au contenu</a>"
    "<header><nav aria-label='Principale'><a href='/'>Accueil</a></nav></header><main id='c'><h1>Titre</h1><h2>Sous-titre</h2>"
    "<form><label for='n'>Nom</label><input id='n' name='n'><button type='submit'>Envoyer</button></form>"
    "<table><tr><th scope='col'>A</th></tr></table><i data-lucide='x' aria-hidden='true'></i></main><footer><p>Pied</p></footer></body></html>"
)


class ContrastesTests(SimpleTestCase):
    def test_formule_wcag(self):
        self.assertAlmostEqual(contraste("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(contraste("#FFFFFF", "#FFFFFF"), 1.0, places=2)
        self.assertEqual(contraste("#123456", "#ABCDEF"), contraste("#ABCDEF", "#123456"))  # symétrique

    def test_toutes_les_couleurs_du_projet_respectent_le_niveau_AA(self):
        for nom, texte, fond, rapport in contrastes_du_projet():
            with self.subTest(nom):
                self.assertGreaterEqual(rapport, SEUIL_TEXTE_NORMAL, f"{texte} sur {fond}")

    def test_les_couleurs_viennent_des_fichiers_css(self):
        couleurs = couleurs_css("app.css", "ui.css")
        for variable in ("--a-text", "--a-muted", "--a-bg", "--a-accent", "--u1", "--u5", "--text", "--muted", "--bg"):
            self.assertIn(variable, couleurs)
        self.assertEqual(len(contrastes_du_projet()), 16)

    def test_un_contraste_insuffisant_serait_detecte(self):
        self.assertLess(contraste("#4A6688", "#0C1A30"), SEUIL_TEXTE_NORMAL)  # le gris « text-gray-400 » du thème sombre ne convient pas au texte


class StructureHtmlTests(SimpleTestCase):
    def test_une_page_correcte_ne_signale_rien(self):
        self.assertEqual(verifier_html(PAGE_PARFAITE), [])

    def test_chaque_defaut_est_detecte(self):
        cas = {
            "sans lang": (PAGE_PARFAITE.replace(" lang='fr'", ""), "sans attribut lang"),
            "sans titre": (PAGE_PARFAITE.replace("<title>Une page</title>", "<title></title>"), "<title> vide"),
            "sans pied": (PAGE_PARFAITE.replace("<footer><p>Pied</p></footer>", ""), "pas de <footer>"),
            "deux main": (PAGE_PARFAITE.replace("</main>", "</main><main></main>"), "2 élément(s) <main>"),
            "nav anonyme": (PAGE_PARFAITE.replace(" aria-label='Principale'", ""), "<nav> sans aria-label"),
            "deux h1": (PAGE_PARFAITE.replace("<h2>Sous-titre</h2>", "<h1>Autre</h1>"), "2 titre(s) h1"),
            "saut de titre": (PAGE_PARFAITE.replace("<h2>", "<h3>").replace("</h2>", "</h3>"), "h1 puis h3"),
            "id en double": (PAGE_PARFAITE.replace("<h1>", "<h1 id='c'>"), "identifiant en double : c"),
            "champ sans étiquette": (PAGE_PARFAITE.replace("<label for='n'>Nom</label>", ""), "champ sans étiquette : n"),
            "bouton muet": (PAGE_PARFAITE.replace("Envoyer</button>", "</button>"), "button sans nom accessible"),
            "image sans alt": (PAGE_PARFAITE.replace("<i data", "<img src='a.png'><i data"), "image sans alt : a.png"),
            "icône exposée": (PAGE_PARFAITE.replace(" aria-hidden='true'", ""), "1 icône(s) sans aria-hidden"),
            "tabindex positif": (PAGE_PARFAITE.replace("<h1>", "<h1 tabindex='3'>"), "1 tabindex positif"),
            "th sans scope": (PAGE_PARFAITE.replace(" scope='col'", ""), "1 cellule(s) <th> sans scope"),
        }
        for nom, (html, attendu) in cas.items():
            with self.subTest(nom):
                self.assertTrue(any(attendu in p for p in verifier_html(html)), verifier_html(html))

    def test_un_champ_dans_son_etiquette_ou_avec_aria_label_est_accepte(self):
        for champ in ("<label>Nom <input name='n'></label>", "<input name='n' aria-label='Nom'>"):
            self.assertEqual(verifier_html(PAGE_PARFAITE.replace("<label for='n'>Nom</label><input id='n' name='n'>", champ)), [])

    def test_un_lien_qui_n_a_que_son_icone_est_signale_mais_pas_s_il_a_un_nom(self):
        muet = PAGE_PARFAITE.replace("Accueil</a>", "<i data-lucide='home' aria-hidden='true'></i></a>")
        self.assertTrue(any("a sans nom accessible" in p for p in verifier_html(muet)))
        nomme = PAGE_PARFAITE.replace("Accueil</a>", "<i data-lucide='home' aria-hidden='true'></i></a>").replace("<a href='/'>", "<a href='/' aria-label='Accueil'>")
        self.assertEqual(verifier_html(nomme), [])


class PagesAccessiblesTests(SimpleTestCase):
    PUBLIQUES = ("/", "/comptes/connexion/", "/patients/inscription/", "/medecins/inscription/", "/comptes/mot-de-passe-oublie/", "/comptes/mot-de-passe-oublie/envoye/", "/comptes/reinitialisation/terminee/")

    def test_les_pages_publiques_n_ont_aucun_defaut(self):
        for url in self.PUBLIQUES:
            with self.subTest(url):
                self.assertEqual(verifier_html(self.client.get(url).content.decode()), [])

    def test_les_liens_internes_de_l_accueil_ont_une_cible(self):
        html = self.client.get("/").content.decode()
        ancres = set(re.findall(r'href="#([^"]+)"', html))
        for ancre in ancres:
            with self.subTest(ancre):
                self.assertIn(f'id="{ancre}"', html)
        self.assertTrue({"contenu", "a-propos", "contact"} <= ancres)

    def test_les_cadres_de_l_application_ont_un_pied_et_un_seul_main(self):
        requete = RequestFactory().get("/")
        requete.user = AnonymousUser()
        page = engines["django"].from_string('{% extends "core/layout.html" %}{% block page %}<h1>Titre</h1>{% endblock %}')
        html = page.render({}, requete)
        self.assertEqual(verifier_html(html), [])
        self.assertIn('<footer class="app-footer">', html)
        self.assertIn("Urgence vitale ?", html)

    def test_aucune_icone_n_est_oubliee_dans_les_gabarits(self):
        manquantes = []
        for dossier in ("core", "patients", "backoffice", "medecins", "templates"):
            for chemin in (RACINE_PROJET / dossier).rglob("*.html"):
                for balise in re.findall(r"<i\b[^>]*data-lucide[^>]*>", chemin.read_text(encoding="utf-8")):
                    if "aria-hidden" not in balise:
                        manquantes.append(f"{chemin.relative_to(RACINE_PROJET)} : {balise[:60]}")
        self.assertEqual(manquantes, [])

    def test_le_focus_clavier_est_visible_partout(self):
        ui = (RACINE_PROJET / "static" / "css" / "ui.css").read_text(encoding="utf-8")
        self.assertRegex(ui, r"a:focus-visible, button:focus-visible")
        self.assertIn("prefers-reduced-motion", ui)
        self.assertEqual(self.client.get("/").content.decode().count('class="skip-link"'), 1)  # lien « Aller au contenu principal »


class ChampsDeFormulaireTests(SimpleTestCase):
    class Formulaire(StyledFormMixin, django_forms.Form):
        nom = django_forms.CharField(label="Nom", help_text="Votre nom de famille.")
        age = django_forms.IntegerField(label="Âge", required=False)

    def rendre(self, donnees=None):
        form = self.Formulaire(donnees)
        return "".join(render_to_string("core/_champ.html", {"field": champ}) for champ in form)

    def test_l_aide_est_reliee_au_champ(self):
        html = self.rendre()
        self.assertIn('aria-describedby="id_nom_aide"', html)
        self.assertIn('<div class="f-help" id="id_nom_aide">Votre nom de famille.</div>', html)
        self.assertNotIn("aria-invalid", html)

    def test_l_erreur_est_annoncee_et_reliee_au_champ(self):
        html = self.rendre({"nom": "", "age": "abc"})
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('aria-describedby="id_nom_aide id_nom_erreur"', html)  # aide puis erreur
        self.assertIn('<div id="id_nom_erreur">', html)
        self.assertIn('role="alert"', html)
        self.assertIn('aria-describedby="id_age_erreur"', html)  # pas d'aide pour ce champ : seulement l'erreur

    def test_un_champ_sans_aide_ni_erreur_reste_inchange(self):
        html = self.rendre({"nom": "Amel", "age": "30"})
        self.assertNotIn("aria-describedby", html.split("id_age")[1])
        self.assertNotIn("aria-invalid", html)

    def test_les_champs_connus_du_navigateur(self):
        connexion = ConnexionForm()
        self.assertEqual(connexion.fields["username"].widget.attrs["autocomplete"], "username")
        self.assertEqual(connexion.fields["password"].widget.attrs["autocomplete"], "current-password")
        from .forms import ChangementMotDePasseForm, DemandeReinitialisationForm, NouveauMotDePasseForm

        compte = User(username="u")
        self.assertEqual(ChangementMotDePasseForm(compte).fields["old_password"].widget.attrs["autocomplete"], "current-password")
        self.assertEqual(ChangementMotDePasseForm(compte).fields["new_password1"].widget.attrs["autocomplete"], "new-password")
        self.assertEqual(NouveauMotDePasseForm(compte).fields["new_password2"].widget.attrs["autocomplete"], "new-password")
        self.assertEqual(DemandeReinitialisationForm().fields["email"].widget.attrs["autocomplete"], "email")

    def test_les_formulaires_du_patient_declarent_leurs_champs(self):
        from patients.forms import CompteForm, FermetureCompteForm, InscriptionPatientForm, ProfilPatientForm

        attendu = {
            InscriptionPatientForm: {"first_name": "given-name", "last_name": "family-name", "email": "email", "telephone": "tel", "date_naissance": "bday", "password1": "new-password"},
            ProfilPatientForm: {"telephone": "tel", "adresse": "street-address", "ville": "address-level2", "date_naissance": "bday"},
            CompteForm: {"first_name": "given-name", "last_name": "family-name", "email": "email"},
        }
        for classe, champs in attendu.items():
            form = classe()
            for nom, valeur in champs.items():
                with self.subTest(classe=classe.__name__, champ=nom):
                    self.assertEqual(form.fields[nom].widget.attrs["autocomplete"], valeur)
        self.assertEqual(FermetureCompteForm(user=User(username="u")).fields["mot_de_passe"].widget.attrs["autocomplete"], "current-password")


class CommandeAuditTests(SimpleTestCase):
    def test_audit_des_pages_publiques(self):
        sortie = io.StringIO()
        call_command("audit_accessibilite", stdout=sortie)
        texte = sortie.getvalue()
        for morceau in ("Contrastes (seuil WCAG AA", "texte principal sur le fond", "Structure des pages", "5 pages vérifiées, 0 avec un défaut ; 0 contraste(s) insuffisant(s)."):
            self.assertIn(morceau, texte)
