from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from patients.models import Triage

from . import views
from .forms import FiltreRendezVousForm, MajRendezVousForm
from .permissions import administrateur_requis, est_administrateur
from .stats import (
    chiffres_cles,
    niveau_effectif,
    nombre_par_patient,
    repartition_par_niveau,
)

User = get_user_model()
RACINE = Path(__file__).resolve().parent.parent


def utilisateur(**kw):
    """Utilisateur non enregistré (aucun accès à la base)."""
    valeurs = {"username": "u", "is_active": True}
    valeurs.update(kw)
    return User(**valeurs)


# --- Droits d'accès --------------------------------------------------------------


class DroitsTests(SimpleTestCase):
    def test_qui_est_administrateur(self):
        self.assertTrue(est_administrateur(utilisateur(is_staff=True)))
        self.assertTrue(est_administrateur(utilisateur(is_superuser=True)))
        self.assertTrue(est_administrateur(utilisateur(role="admin")))

    def test_les_autres_ne_le_sont_pas(self):
        for role in ("patient", "medecin", "infirmier", "pharmacie", "laboratoire"):
            self.assertFalse(est_administrateur(utilisateur(role=role)), role)

    def test_un_compte_desactive_n_a_aucun_acces(self):
        self.assertFalse(est_administrateur(utilisateur(is_staff=True, is_active=False)))

    def test_un_visiteur_anonyme_n_est_pas_administrateur(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(est_administrateur(AnonymousUser()))

    def appeler(self, user, chemin="/backoffice/rendez-vous/?statut=en_attente"):
        @administrateur_requis
        def vue(request):
            return HttpResponse("ok")

        requete = RequestFactory().get(chemin)
        requete.user = user
        return vue(requete)

    def test_anonyme_renvoye_vers_la_connexion_avec_retour_prevu(self):
        from django.contrib.auth.models import AnonymousUser

        reponse = self.appeler(AnonymousUser())
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/?next="))
        self.assertIn("rendez-vous", reponse["Location"])

    def test_un_patient_recoit_une_interdiction(self):
        with self.assertRaises(PermissionDenied):
            self.appeler(utilisateur(role="patient"))

    def test_le_personnel_entre(self):
        self.assertEqual(self.appeler(utilisateur(role="admin", is_staff=True)).status_code, 200)

    def test_toutes_les_vues_sont_protegees(self):
        for nom in ("tableau_de_bord", "rendez_vous", "rendez_vous_detail", "patients", "patient_detail", "symptomes"):
            vue = getattr(views, nom)
            requete = RequestFactory().get("/backoffice/")
            requete.user = utilisateur(role="patient")
            args = ("x",) if nom.endswith("_detail") else ()
            with self.subTest(vue=nom):
                with self.assertRaises(PermissionDenied):
                    vue(requete, *args)

    def test_acces_anonyme_aux_urls_reelles(self):
        for url in ("/backoffice/", "/backoffice/rendez-vous/", "/backoffice/patients/", "/backoffice/symptomes/"):
            with self.subTest(url=url):
                reponse = self.client.get(url)
                self.assertEqual(reponse.status_code, 302)
                self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))


# --- URLs --------------------------------------------------------------------------


class UrlsTests(SimpleTestCase):
    def test_les_adresses(self):
        self.assertEqual(reverse("backoffice:tableau_de_bord"), "/backoffice/")
        self.assertEqual(reverse("backoffice:rendez_vous"), "/backoffice/rendez-vous/")
        self.assertEqual(reverse("backoffice:rendez_vous_detail", args=["abc"]), "/backoffice/rendez-vous/abc/")
        self.assertEqual(reverse("backoffice:patients"), "/backoffice/patients/")
        self.assertEqual(reverse("backoffice:patient_detail", args=["abc"]), "/backoffice/patients/abc/")
        self.assertEqual(reverse("backoffice:symptomes"), "/backoffice/symptomes/")

    def test_chaque_adresse_pointe_vers_la_bonne_vue(self):
        self.assertIs(resolve("/backoffice/").func, views.tableau_de_bord)
        self.assertIs(resolve("/backoffice/rendez-vous/").func, views.rendez_vous)
        self.assertIs(resolve("/backoffice/patients/x/").func, views.patient_detail)


# --- Statistiques --------------------------------------------------------------------


class StatsTests(SimpleTestCase):
    LIGNES = [
        (1, None, "en_attente"),
        (1, None, "en_consultation"),
        (2, None, "en_attente"),
        (3, 1, "en_attente"),      # requalifié par le médecin : compte comme niveau 1
        (5, None, "termine"),
        (4, None, "annule"),
        (5, None, "en_attente"),
    ]

    def test_le_niveau_du_medecin_prime(self):
        self.assertEqual(niveau_effectif(3, 1), 1)
        self.assertEqual(niveau_effectif(3, None), 3)
        self.assertEqual(niveau_effectif(None, None), None)

    def test_repartition_ne_compte_que_les_demandes_actives(self):
        r = {x["niveau"]: x["nombre"] for x in repartition_par_niveau(self.LIGNES)}
        self.assertEqual(r, {1: 3, 2: 1, 3: 0, 4: 0, 5: 1})  # terminée et annulée exclues

    def test_repartition_contient_toujours_cinq_niveaux_dans_l_ordre(self):
        r = repartition_par_niveau([])
        self.assertEqual([x["niveau"] for x in r], [1, 2, 3, 4, 5])
        self.assertTrue(all(x["nombre"] == 0 and x["pourcentage"] == 0 for x in r))  # pas de division par zéro

    def test_pourcentages_relatifs_a_la_plus_grande_barre(self):
        r = {x["niveau"]: x["pourcentage"] for x in repartition_par_niveau(self.LIGNES)}
        self.assertEqual(r[1], 100)
        self.assertEqual(r[2], 33)
        self.assertEqual(r[3], 0)

    def test_libelles_des_niveaux(self):
        libelles = [x["libelle"] for x in repartition_par_niveau([])]
        self.assertEqual(libelles, ["Vital", "Très urgent", "Urgent", "Standard", "Non urgent"])

    def test_chiffres_cles(self):
        k = chiffres_cles(self.LIGNES, nb_patients=9)
        self.assertEqual(k["total"], 7)
        self.assertEqual(k["en_attente"], 4)
        self.assertEqual(k["urgentes"], 4)  # niveaux effectifs 1, 1, 2 et 1 (requalifié) parmi les actives
        self.assertEqual(k["terminees"], 1)
        self.assertEqual(k["annulees"], 1)
        self.assertEqual(k["patients"], 9)

    def test_les_cas_termines_ne_sont_plus_urgents(self):
        self.assertEqual(chiffres_cles([(1, None, "termine"), (1, None, "annule")], 0)["urgentes"], 0)

    def test_aucune_demande(self):
        k = chiffres_cles([], 0)
        self.assertEqual((k["total"], k["en_attente"], k["urgentes"]), (0, 0, 0))

    def test_nombre_de_demandes_par_patient(self):
        c = nombre_par_patient(["a", "b", "a", "a"])
        self.assertEqual((c["a"], c["b"], c["zzz"]), (3, 1, 0))


# --- Formulaires -------------------------------------------------------------------------


class FormulairesTests(SimpleTestCase):
    def test_le_filtre_accepte_une_recherche_vide(self):
        self.assertTrue(FiltreRendezVousForm(data={}).is_valid())

    def test_le_filtre_refuse_une_valeur_inconnue(self):
        for champ, valeur in (("statut", "inconnu"), ("niveau", "9"), ("medecin", "zzz")):
            with self.subTest(champ=champ):
                self.assertFalse(FiltreRendezVousForm(data={champ: valeur}).is_valid())

    def test_le_filtre_propose_tous_les_niveaux_et_statuts(self):
        f = FiltreRendezVousForm()
        self.assertEqual([c[0] for c in f.fields["niveau"].choices], ["", "1", "2", "3", "4", "5"])
        self.assertEqual(
            [c[0] for c in f.fields["statut"].choices],
            ["", "en_attente", "en_consultation", "termine", "annule"],
        )
        self.assertEqual(len(f.fields["medecin"].choices), 7)  # « Tous » + 6 médecins

    def test_l_administrateur_ne_peut_modifier_que_statut_et_niveau_medecin(self):
        self.assertEqual(list(MajRendezVousForm.base_fields), ["statut", "niveau_medecin"])

    def test_le_niveau_du_medecin_est_facultatif(self):
        f = MajRendezVousForm(data={"statut": "termine", "niveau_medecin": ""})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertIsNone(f.cleaned_data["niveau_medecin"])

    def test_niveau_et_statut_hors_choix_refuses(self):
        self.assertFalse(MajRendezVousForm(data={"statut": "termine", "niveau_medecin": "9"}).is_valid())
        self.assertFalse(MajRendezVousForm(data={"statut": "n'importe quoi", "niveau_medecin": ""}).is_valid())

    def test_le_score_ne_peut_pas_etre_falsifie_par_le_formulaire(self):
        f = MajRendezVousForm(data={"statut": "termine", "niveau_medecin": "2", "score": "0", "niveau": "5"})
        self.assertTrue(f.is_valid())
        self.assertNotIn("score", f.cleaned_data)
        self.assertNotIn("niveau", f.cleaned_data)


# --- Gabarits ------------------------------------------------------------------------------


def fausse_demande(niveau=1, statut="en_attente"):
    labels = {1: "1 – Vital", 2: "2 – Très urgent", 3: "3 – Urgent", 4: "4 – Standard", 5: "5 – Non urgent"}
    class Patient:
        pk = "p1"

        def __str__(self):
            return "Amel Trabelsi"

    patient = Patient()
    return SimpleNamespace(
        pk="t1", patient=patient, cree_le=None, medecin_nom="Dr Sara Benali", medecin_specialite="Médecine générale",
        niveau_effectif=niveau, niveau=niveau, niveau_medecin=None, get_niveau_display=labels[niveau], score=27,
        statut=statut, get_statut_display={"en_attente": "En attente", "termine": "Terminé"}.get(statut, statut),
        explication="Niveau 1 (score 27).", symptomes=[], texte_libre="", drapeaux_rouges=[],
        constantes=None, auto_evaluation_resume=lambda: [],
    )


class GabaritsTests(SimpleTestCase):
    def requete(self, nom="tableau_de_bord"):
        requete = RequestFactory().get("/backoffice/")
        requete.user = utilisateur(role="admin", is_staff=True, first_name="Admin")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def test_le_tableau_de_bord_affiche_les_chiffres_et_les_barres(self):
        html = render_to_string("backoffice/tableau_de_bord.html", {
            "kpis": chiffres_cles(StatsTests.LIGNES, 9),
            "repartition": repartition_par_niveau(StatsTests.LIGNES),
            "derniers": [fausse_demande()],
        }, self.requete())
        self.assertIn("Demandes au total", html)
        self.assertIn("kpi-alert", html)  # des cas urgents existent : le chiffre est mis en avant
        self.assertEqual(html.count("bar-row req-"), 5)
        self.assertIn('style="width: 100%"', html)
        self.assertIn("Amel Trabelsi", html)

    def test_pas_d_alerte_sans_cas_urgent(self):
        html = render_to_string("backoffice/tableau_de_bord.html", {
            "kpis": chiffres_cles([(5, None, "en_attente")], 1),
            "repartition": repartition_par_niveau([(5, None, "en_attente")]),
            "derniers": [],
        }, self.requete())
        self.assertNotIn("kpi-alert", html)
        self.assertIn("Aucune demande pour le moment", html)

    def test_la_navigation_marque_la_page_courante(self):
        html = render_to_string("backoffice/tableau_de_bord.html", {
            "kpis": chiffres_cles([], 0), "repartition": repartition_par_niveau([]), "derniers": [],
        }, self.requete("tableau_de_bord"))
        self.assertEqual(html.count('aria-current="page"'), 1)
        for lien in ("/backoffice/rendez-vous/", "/backoffice/patients/", "/backoffice/symptomes/", "/admin/"):
            self.assertIn(f'href="{lien}"', html)

    def test_les_tableaux_ont_des_en_tetes_accessibles(self):
        html = render_to_string("backoffice/tableau_de_bord.html", {
            "kpis": chiffres_cles([], 0), "repartition": repartition_par_niveau([]), "derniers": [],
        }, self.requete())
        self.assertIn('<th scope="col">', html)

    def test_la_pagination(self):
        from django.core.paginator import Paginator

        page = Paginator(list(range(30)), 12).get_page(2)
        html = render_to_string("backoffice/_pager.html", {"page": page, "parametres": "statut=termine"})
        self.assertIn("Page 2 sur 3", html)
        self.assertIn("30 résultats", html)
        self.assertIn("?statut=termine&amp;page=1", html)  # les filtres sont conservés
        self.assertIn("?statut=termine&amp;page=3", html)

    def test_pas_de_pagination_pour_une_seule_page(self):
        from django.core.paginator import Paginator

        page = Paginator(list(range(5)), 12).get_page(1)
        self.assertNotIn("Pagination", render_to_string("backoffice/_pager.html", {"page": page, "parametres": ""}))

    def test_tous_les_gabarits_du_backoffice_existent_et_etendent_le_bon_cadre(self):
        for nom in ("tableau_de_bord", "rendez_vous", "rendez_vous_detail", "patients", "patient_detail", "symptomes"):
            src = (RACINE / "backoffice" / "templates" / "backoffice" / f"{nom}.html").read_text(encoding="utf-8")
            with self.subTest(gabarit=nom):
                self.assertIn('extends "backoffice/layout.html"', src)
        layout = (RACINE / "backoffice" / "templates" / "backoffice" / "layout.html").read_text(encoding="utf-8")
        self.assertIn('extends "core/layout.html"', layout)

    def test_aucun_fond_blanc(self):
        import re

        for chemin in (RACINE / "backoffice" / "templates").rglob("*.html"):
            self.assertIsNone(re.search(r"bg-white(?!/(?:[1-9]|10)(?![0-9]))", chemin.read_text(encoding="utf-8")), chemin.name)


class StylesBackofficeTests(SimpleTestCase):
    def setUp(self):
        self.css = (RACINE / "static" / "css" / "app.css").read_text(encoding="utf-8")

    def test_les_classes_utilisees_par_les_pages_existent(self):
        for classe in (".kpi-grid", ".kpi-num", ".kpi-alert", ".bar-row", ".bar-fill", ".bar-track", ".tbl",
                       ".table-wrap", ".pager", ".filters", ".dl", ".st-en_attente", ".st-en_consultation",
                       ".st-termine", ".st-annule"):
            self.assertIn(classe, self.css, classe)

    def test_un_tableau_trop_large_defile_dans_son_cadre_et_pas_la_page(self):
        self.assertIn("overflow-x: auto", self.css)

    def test_les_statuts_ne_reposent_pas_que_sur_la_couleur(self):
        # chaque badge de statut porte aussi son libellé écrit dans la page
        src = (RACINE / "backoffice" / "templates" / "backoffice" / "rendez_vous.html").read_text(encoding="utf-8")
        self.assertIn("get_statut_display", src)

    def test_le_modele_expose_les_statuts_attendus_par_les_badges(self):
        for valeur, _ in Triage.Statut.choices:
            self.assertIn(f".st-{valeur}", self.css)
