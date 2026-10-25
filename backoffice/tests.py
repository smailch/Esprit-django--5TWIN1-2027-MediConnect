from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from unittest import mock

from bson import ObjectId as ObjectId_

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
        for lien in ("/backoffice/rendez-vous/", "/backoffice/file-attente/", "/backoffice/patients/", "/backoffice/parametres/"):
            self.assertIn(f'href="{lien}"', html)
        self.assertEqual(html.count('class="nav-item"'), 5)  # cinq entrées au plus : lisible sur mobile

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


# --- File d'attente : statistiques, formulaires, pages, accès ----------------------------------------
import datetime  # noqa: E402

from patients import file_attente as fa  # noqa: E402
from patients.models import ReglageTriage  # noqa: E402

from .forms import ReglageTriageForm  # noqa: E402
from .stats import a_surveiller, chiffres_file  # noqa: E402


class FauxPatient:
    def __init__(self, nom="Amel"):
        self.nom, self.pk = nom, "pat"

    def __str__(self):
        return self.nom


def demande_annotee(etat="dans_les_temps", ratio=0.2, niveau=3, protegee=False, depassements=0, creneau=None, nom="Amel"):
    delai = fa.Delai(etat=etat, echeance=datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.timezone.utc),
                     cible_min=120, ecoule_min=ratio * 120, reste_min=120 - ratio * 120, ratio=ratio)
    return SimpleNamespace(
        pk="p1", delai=delai, protegee=protegee, nb_depassements=depassements, creneau=creneau, niveau_effectif=niveau,
        patient=FauxPatient(nom), medecin_nom="Dr Sara Benali", medecin_specialite="MG",
        cree_le=datetime.datetime(2026, 10, 21, 8, 0, tzinfo=datetime.timezone.utc), place=(1, 2),
        prise_en_charge_estimee=datetime.datetime(2026, 10, 21, 10, 0, tzinfo=datetime.timezone.utc), statut="en_attente",
        score=5, get_statut_display=lambda: "En attente", medecin_id="m1",
    )


class FileStatsTests(SimpleTestCase):
    def test_chiffres_de_la_file(self):
        etats = [("dans_les_temps", False), ("a_risque", False), ("en_retard", True), ("en_retard", False), ("planifie", False)]
        self.assertEqual(chiffres_file(etats), {"total": 5, "dans_les_temps": 1, "a_risque": 1, "en_retard": 2, "planifies": 1, "protegees": 1})

    def test_file_vide(self):
        self.assertEqual(chiffres_file([]), {"total": 0, "dans_les_temps": 0, "a_risque": 0, "en_retard": 0, "planifies": 0, "protegees": 0})

    def test_a_surveiller_retards_d_abord_puis_les_plus_avances(self):
        a = demande_annotee("a_risque", 0.9)
        b = demande_annotee("en_retard", 1.2)
        c = demande_annotee("en_retard", 3.0)
        d = demande_annotee("dans_les_temps", 0.1)
        e = demande_annotee("a_risque", 0.8)
        self.assertEqual(a_surveiller([a, b, c, d, e]), [c, b, a, e])  # la demande dans les temps n'y figure pas

    def test_a_surveiller_est_limite(self):
        demandes = [demande_annotee("en_retard", 1 + i / 10) for i in range(10)]
        self.assertEqual(len(a_surveiller(demandes)), 6)
        self.assertEqual(len(a_surveiller(demandes, limite=3)), 3)
        self.assertEqual(a_surveiller([]), [])


class MajRendezVousDepassementsTests(SimpleTestCase):
    def maj(self, avant, apres):
        triage = Triage(medecin_id="m1", niveau=3, statut=avant, cree_le=datetime.datetime(2026, 10, 21, 8, 0, tzinfo=datetime.timezone.utc))
        triage.pk = ObjectId_()
        form = MajRendezVousForm({"statut": apres, "niveau_medecin": ""}, instance=triage)
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(Triage, "save"), mock.patch.object(Triage, "enregistrer_depassements", return_value=1) as comptage:
            form.save()
        return comptage

    def test_passage_en_consultation_compte_les_depassements(self):
        self.maj("en_attente", "en_consultation").assert_called_once_with()

    def test_les_autres_changements_ne_comptent_rien(self):
        for avant, apres in (("en_consultation", "termine"), ("en_attente", "annule"), ("en_consultation", "en_consultation"), ("termine", "termine")):
            with self.subTest(avant=avant, apres=apres):
                self.maj(avant, apres).assert_not_called()


class ReglageTriageFormTests(SimpleTestCase):
    DONNEES = {"delai_niveau_2": 30, "delai_niveau_3": 120, "delai_niveau_4": 480, "delai_niveau_5": 1440,
               "plafond_depassements": 5, "seuil_risque": 75, "duree_consultation": 20, "facteur_garantie": 3, "seuil_modele": 85}

    def test_formulaire_valide(self):
        self.assertTrue(ReglageTriageForm(self.DONNEES).is_valid())

    def test_champs_proposes(self):
        self.assertEqual(list(ReglageTriageForm.base_fields), list(self.DONNEES))  # pas de « modifie_le »

    def test_delais_dans_le_desordre_refuses(self):
        f = ReglageTriageForm({**self.DONNEES, "delai_niveau_3": 20})
        self.assertFalse(f.is_valid())
        self.assertIn("augmenter avec le niveau", str(f.errors))

    def test_valeurs_hors_bornes_refusees(self):
        for champ, valeur in (("plafond_depassements", 0), ("seuil_risque", 99), ("duree_consultation", 500), ("delai_niveau_2", 1)):
            with self.subTest(champ=champ):
                self.assertIn(champ, ReglageTriageForm({**self.DONNEES, champ: valeur}).errors)

    def test_champs_obligatoires(self):
        self.assertEqual(set(ReglageTriageForm({}).errors), set(self.DONNEES))

    def test_style_des_champs(self):
        self.assertTrue(all(c.widget.attrs.get("class") == "field" for c in ReglageTriageForm().fields.values()))


class FilePagesBackofficeTests(SimpleTestCase):
    def requete(self, nom="file_attente"):
        requete = RequestFactory().get("/backoffice/file-attente/")
        requete.user = utilisateur(role="admin", is_staff=True, first_name="Admin")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def section(self, **kw):
        return {"medecin": {"id": "m1", "nom": "Dr Sara Benali", "specialite": "MG"}, "file": kw.get("file", []),
                "planning": kw.get("planning", []), "en_retard": kw.get("en_retard", 0), "a_risque": kw.get("a_risque", 0)}

    def rendre(self, sections, chiffres=None):
        reglage = fa.DEFAUT
        return render_to_string("backoffice/file_attente.html", {
            "sections": sections, "chiffres": chiffres or chiffres_file([]),
            "delais": [(n, f"niveau {n}", reglage.delais[n]) for n in (2, 3, 4, 5)], "reglage": reglage,
        }, self.requete())

    def test_adresses(self):
        self.assertEqual(reverse("backoffice:file_attente"), "/backoffice/file-attente/")
        self.assertEqual(reverse("backoffice:parametres"), "/backoffice/parametres/")
        self.assertIs(resolve("/backoffice/file-attente/").func, views.file_attente)
        self.assertIs(resolve("/backoffice/parametres/").func, views.parametres)

    def test_acces_reserve_aux_administrateurs(self):
        for nom in ("file_attente", "parametres"):
            with self.subTest(vue=nom):
                requete = RequestFactory().get("/x/")
                requete.user = utilisateur(role="patient")
                with self.assertRaises(PermissionDenied):
                    getattr(views, nom)(requete)
                from django.contrib.auth.models import AnonymousUser

                requete.user = AnonymousUser()
                reponse = getattr(views, nom)(requete)
                self.assertEqual(reponse.status_code, 302)
                self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))

    def test_page_avec_file_et_planning(self):
        a = demande_annotee("en_retard", 1.3, niveau=4, depassements=2, nom="Karim")
        b = demande_annotee("planifie", 0, creneau=datetime.datetime(2026, 10, 22, 9, 0, tzinfo=datetime.timezone.utc), nom="Sonia")
        html = self.rendre([self.section(file=[a], planning=[b], en_retard=1)], chiffres_file([("en_retard", False), ("planifie", False)]))
        for texte in ("File d'attente", "Dr Sara Benali", "Règles en vigueur", "1 en file", "1 rendez-vous", "1 en retard", "Rendez-vous fixés",
                      "2 / 5", ">En retard<", ">Rendez-vous fixé<", "Karim", "Sonia"):
            self.assertIn(texte, html)
        self.assertIn("kpi-alert", html)

    def test_demande_protegee_signalee(self):
        html = self.rendre([self.section(file=[demande_annotee(protegee=True, depassements=5)])])
        self.assertIn("protégée", html)
        self.assertNotIn("5 / 5", html)

    def test_file_vide(self):
        html = self.rendre([self.section()])
        self.assertIn("Aucun patient dans la file", html)
        self.assertNotIn("kpi-alert", html)

    def test_regles_affichees_avec_les_delais_courants(self):
        html = self.rendre([self.section()])
        for duree in ("30 min", "2 h", "8 h", "24 h"):
            self.assertIn(duree, html)
        self.assertIn("5 fois", html)
        self.assertIn("3 fois", html)  # garantie
        self.assertIn("Vital : hors file", html)

    def test_tableau_tableau_accessible(self):
        html = self.rendre([self.section(file=[demande_annotee()])])
        self.assertIn('<caption class="sr-only">', html)
        self.assertIn('scope="col"', html)

    def test_parametres(self):
        html = render_to_string("backoffice/parametres.html", {"form": ReglageTriageForm(instance=ReglageTriage())}, self.requete("parametres"))
        for texte in ("Paramètres", "File d'attente", "Enregistrer", "Valeurs par défaut", "Comment ça marche", "Catalogue des symptômes",
                      "Administration Django", "csrfmiddlewaretoken", "Dépassements maximum", "Garantie : passage prioritaire"):
            self.assertIn(texte, html)
        self.assertEqual(html.count('name="delai_niveau_'), 4)

    def test_parametres_erreurs_annoncees(self):
        form = ReglageTriageForm({**ReglageTriageFormTests.DONNEES, "delai_niveau_3": 20}, instance=ReglageTriage())
        form.is_valid()
        html = render_to_string("backoffice/parametres.html", {"form": form}, self.requete("parametres"))
        self.assertIn('role="alert"', html)

    def test_tableau_de_bord_avec_file_et_a_surveiller(self):
        retard = demande_annotee("en_retard", 1.5, nom="Hichem")
        html = render_to_string("backoffice/tableau_de_bord.html", {
            "kpis": chiffres_cles([], 0), "repartition": repartition_par_niveau([]), "derniers": [],
            "file": chiffres_file([("en_retard", False), ("a_risque", False), ("a_risque", True)]), "a_surveiller": [retard],
        }, self.requete("tableau_de_bord"))
        self.assertIn("Demandes en retard", html)
        self.assertIn("kpi-alert", html)
        self.assertIn("kpi-warn", html)
        self.assertIn("À surveiller", html)
        self.assertIn("Hichem", html)
        self.assertIn("Demandes protégées", html)

    def test_tableau_de_bord_sans_demande_a_surveiller(self):
        html = render_to_string("backoffice/tableau_de_bord.html", {
            "kpis": chiffres_cles([], 0), "repartition": repartition_par_niveau([]), "derniers": [],
            "file": chiffres_file([("dans_les_temps", False)]), "a_surveiller": [],
        }, self.requete("tableau_de_bord"))
        self.assertNotIn("À surveiller", html)
        self.assertNotIn("kpi-warn", html)

    def test_detail_d_une_demande_montre_le_delai(self):
        t = demande_annotee("a_risque", 0.8, depassements=3)
        t.explication, t.symptomes, t.drapeaux_rouges = "e", [], []
        t.texte_libre, t.constantes, t.niveau, t.niveau_medecin = "", None, 3, None
        t.get_niveau_display, t.niveau_effectif = (lambda: "3 – Urgent"), 3
        t.auto_evaluation_resume = lambda: []
        t.auto_evaluation = None
        form = MajRendezVousForm(instance=Triage(statut="en_attente", niveau=3))
        html = render_to_string("backoffice/rendez_vous_detail.html", {"triage": t, "form": form, "place": (1, 2), "allergies_severes": [], "reglage": fa.DEFAUT}, self.requete("rendez_vous_detail"))
        for texte in ("Délai de prise en charge", ">À risque<", "Dépassements subis", "3 sur 5", "Délai cible du niveau 3", "2 h", "Prise en charge estimée"):
            self.assertIn(texte, html)
        self.assertIn('role="progressbar"', html)

    def test_detail_d_un_rendez_vous_fixe(self):
        t = demande_annotee("planifie", 0, creneau=datetime.datetime(2026, 10, 22, 9, 0, tzinfo=datetime.timezone.utc))
        t.explication, t.symptomes, t.drapeaux_rouges = "e", [], []
        t.texte_libre, t.constantes, t.niveau, t.niveau_medecin = "", None, 3, None
        t.get_niveau_display = lambda: "3 – Urgent"
        t.auto_evaluation_resume = lambda: []
        form = MajRendezVousForm(instance=Triage(statut="en_attente", niveau=3))
        html = render_to_string("backoffice/rendez_vous_detail.html", {"triage": t, "form": form, "place": None, "allergies_severes": [], "reglage": fa.DEFAUT}, self.requete("rendez_vous_detail"))
        self.assertIn("Rendez-vous fixé", html)
        self.assertNotIn('role="progressbar"', html)
        self.assertNotIn("Dépassements subis", html)

    def test_la_liste_des_rendez_vous_a_une_colonne_delai(self):
        from django.core.paginator import Paginator

        t = demande_annotee("en_retard", 1.2)
        t.score = 5
        t2 = demande_annotee()
        t2.delai = None
        page = Paginator([t, t2], 12).get_page(1)
        from .forms import FiltreRendezVousForm

        html = render_to_string("backoffice/rendez_vous.html", {"filtre": FiltreRendezVousForm(), "page": page, "parametres": "", "filtres_actifs": False}, self.requete("rendez_vous"))
        self.assertIn('<th scope="col">Délai</th>', html)
        self.assertIn(">En retard<", html)
        self.assertIn('class="muted">—</span>', html)

    def test_la_navigation_garde_cinq_entrees_avec_file_et_parametres(self):
        html = render_to_string("backoffice/parametres.html", {"form": ReglageTriageForm(instance=ReglageTriage())}, self.requete("parametres"))
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn("File d&#x27;attente</span>", html.replace("File d'attente</span>", "File d&#x27;attente</span>"))

    def test_symptomes_reste_sous_parametres_dans_le_menu(self):
        html = render_to_string("backoffice/symptomes.html", {"symptomes": []}, self.requete("symptomes"))
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn('href="/backoffice/parametres/" class="nav-item" aria-current="page"', html)


# --- Compte rendu de consultation, patients (filtres, export CSV, désactivation) ---------------------------------
import csv  # noqa: E402
import io  # noqa: E402

from django.contrib.auth.models import AnonymousUser  # noqa: E402
from django.db.models import Q  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.utils import proteger_tableur  # noqa: E402
from patients.models import Allergie, Consultation, Patient, SymptomeDeclare  # noqa: E402

from .forms import ConsultationForm, FiltrePatientForm, _il_y_a_ans, consultation_pour  # noqa: E402

AUJOURDHUI = datetime.date(2026, 10, 22)
TUNIS_ = datetime.timezone(datetime.timedelta(hours=1))


def un_patient_de_liste(prenom="Amel", nom="Zouari", actif=True, ville="Tunis", staff=False, **kw):
    """Patient non enregistré, avec son compte (aucun accès à la base)."""
    patient = Patient(pk=ObjectId_(), date_naissance=datetime.date(1990, 5, 4), sexe="F", telephone="20111222", ville=ville, **kw)
    patient.user = User(username=prenom.lower(), first_name=prenom, last_name=nom, email=f"{prenom.lower()}@exemple.tn", is_active=actif, is_staff=staff)
    patient.cree_le = datetime.datetime(2026, 9, 1, 9, 0, tzinfo=TUNIS_)
    return patient


class ListeFiltrable(list):
    """Faux QuerySet : une liste qui note les filtres demandés."""

    def __init__(self, *elements):
        super().__init__(elements)
        self.filtres = []

    def filter(self, *args, **kwargs):
        self.filtres.append((args, kwargs))
        return self


def requete_admin(adresse="/backoffice/patients/", methode="get", donnees=None, nom="patients"):
    requete = getattr(RequestFactory(), methode)(adresse, donnees or {})
    requete.user = utilisateur(role="admin", is_staff=True, first_name="Admin")
    requete.resolver_match = SimpleNamespace(url_name=nom)
    return requete


class ConsultationFormulaireTests(SimpleTestCase):
    DONNEES = {
        "cr-date": "2026-10-20T09:30", "cr-motif": "Toux", "cr-resume": "Toux depuis trois jours.",
        "cr-diagnostic": "Bronchite", "cr-prescription": "Amoxicilline", "cr-recommandations": "Repos",
    }

    def formulaire(self, **remplace):
        donnees = {**self.DONNEES, **remplace}
        return ConsultationForm(donnees, instance=Consultation(medecin_nom="Dr Sara Benali"), prefix="cr")

    def test_valide(self):
        form = self.formulaire()
        self.assertTrue(form.is_valid(), form.errors)
        date = form.cleaned_data["date"]
        self.assertEqual((date.year, date.month, date.day, date.hour, date.minute), (2026, 10, 20, 9, 30))
        self.assertIsNotNone(date.tzinfo)  # une heure saisie est une heure de Tunis, pas une heure « sans fuseau »

    def test_le_compte_rendu_est_obligatoire_le_reste_facultatif(self):
        self.assertIn("resume", self.formulaire(**{"cr-resume": ""}).errors)
        form = self.formulaire(**{"cr-motif": "", "cr-diagnostic": "", "cr-prescription": "", "cr-recommandations": ""})
        self.assertTrue(form.is_valid(), form.errors)

    def test_la_date_ne_peut_pas_etre_dans_le_futur(self):
        demain = (timezone.localtime() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        form = self.formulaire(**{"cr-date": demain})
        self.assertFalse(form.is_valid())
        self.assertIn("date", form.errors)

    def test_champs_proposes_et_style(self):
        form = ConsultationForm(prefix="cr")
        self.assertEqual(list(form.fields), ["date", "motif", "resume", "diagnostic", "prescription", "recommandations"])
        self.assertTrue(all(c.widget.attrs.get("class") == "field" for c in form.fields.values()))
        self.assertEqual(form.fields["date"].widget.input_type, "datetime-local")


class ConsultationPourTests(SimpleTestCase):
    def triage(self):
        t = Triage(patient=un_patient_de_liste(), medecin_id="m1", medecin_nom="Dr Sara Benali", medecin_specialite="Médecine générale",
                   symptomes=[SymptomeDeclare(nom="Toux", poids=2), SymptomeDeclare(nom="Fièvre", poids=3)])
        t.pk = ObjectId_()
        return t

    def test_le_compte_rendu_existant_est_repris(self):
        existante = Consultation(medecin_nom="Dr X", resume="déjà là")
        with mock.patch.object(Consultation.objects, "filter") as filtre:
            filtre.return_value.first.return_value = existante
            self.assertIs(consultation_pour(self.triage()), existante)

    def test_sinon_un_compte_rendu_vierge_prerempli(self):
        triage = self.triage()
        with mock.patch.object(Consultation.objects, "filter") as filtre:
            filtre.return_value.first.return_value = None
            c = consultation_pour(triage)
        self.assertEqual((c.patient, c.triage, c.medecin_nom, c.medecin_specialite), (triage.patient, triage, "Dr Sara Benali", "Médecine générale"))
        self.assertEqual(c.motif, "Toux, Fièvre")  # le motif part des symptômes déclarés
        self.assertIsNone(c.pk)


class RendezVousDetailConsultationTests(SimpleTestCase):
    def triage(self, statut="en_consultation"):
        t = Triage(patient=un_patient_de_liste(), medecin_id="m1", medecin_nom="Dr Sara Benali", medecin_specialite="Médecine générale", niveau=3,
                   statut=statut, explication="e", symptomes=[SymptomeDeclare(nom="Toux", poids=2)])
        t.pk = ObjectId_()
        t.cree_le = datetime.datetime(2026, 10, 20, 8, 0, tzinfo=TUNIS_)
        return t

    def appeler(self, triage, donnees=None):
        requete = requete_admin(f"/backoffice/rendez-vous/{triage.pk}/", "post" if donnees is not None else "get", donnees, "rendez_vous_detail")
        vierge = Consultation(patient=triage.patient, triage=triage, medecin_nom=triage.medecin_nom, motif="Toux")
        espions = SimpleNamespace(triage_save=mock.Mock(), consultation_save=mock.Mock(), messages=mock.Mock())
        with mock.patch.object(views, "objet_ou_404", return_value=triage), mock.patch.object(views, "consultation_pour", return_value=vierge), \
                mock.patch.object(views, "messages", espions.messages), mock.patch.object(Triage, "save", espions.triage_save), \
                mock.patch.object(Consultation, "save", espions.consultation_save), mock.patch.object(Triage, "enregistrer_depassements"), \
                mock.patch.object(Allergie.objects, "filter", return_value=[]), mock.patch.object(views.suivi, "reglage_actuel", return_value=fa.DEFAUT), \
                mock.patch.object(views.suivi, "prevenir_des_changements"):
            reponse = views.rendez_vous_detail(requete, str(triage.pk))
        return reponse, espions, vierge

    def champs(self, **remplace):
        valeurs = {"statut": "termine", "niveau_medecin": "", "cr-date": "2026-10-21T10:00", "cr-motif": "Toux", "cr-resume": "Toux depuis trois jours.",
                   "cr-diagnostic": "Bronchite", "cr-prescription": "Amoxicilline", "cr-recommandations": "Repos"}
        valeurs.update(remplace)
        return valeurs

    def test_la_page_propose_le_compte_rendu(self):
        reponse, _, _ = self.appeler(self.triage())
        html = reponse.content.decode()
        for texte in ("Compte rendu de la consultation", 'id="compte-rendu"', 'name="cr-resume"', 'name="cr-prescription"', 'value="Toux"',
                      "Obligatoire quand le statut passe à", "bloc.hidden = statut.value !== "):
            self.assertIn(texte, html)

    def test_terminer_un_rendez_vous_enregistre_le_compte_rendu(self):
        reponse, espions, vierge = self.appeler(self.triage(), self.champs())
        self.assertEqual(reponse.status_code, 302)
        espions.triage_save.assert_called_once()
        espions.consultation_save.assert_called_once()
        self.assertEqual((vierge.resume, vierge.diagnostic, vierge.prescription, vierge.recommandations), ("Toux depuis trois jours.", "Bronchite", "Amoxicilline", "Repos"))
        self.assertIn("compte rendu est dans le dossier du patient", espions.messages.success.call_args.args[1])

    def test_sans_compte_rendu_on_ne_peut_pas_terminer(self):
        reponse, espions, _ = self.appeler(self.triage(), self.champs(**{"cr-resume": ""}))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Ce champ est obligatoire.", reponse.content.decode())
        espions.triage_save.assert_not_called()  # le statut ne change pas tant que le compte rendu manque
        espions.consultation_save.assert_not_called()

    def test_un_autre_statut_ignore_le_compte_rendu(self):
        for statut in ("annule", "en_attente", "en_consultation"):
            with self.subTest(statut=statut):
                reponse, espions, _ = self.appeler(self.triage(), self.champs(statut=statut, **{"cr-resume": ""}))
                self.assertEqual(reponse.status_code, 302)
                espions.triage_save.assert_called_once()
                espions.consultation_save.assert_not_called()
                self.assertNotIn("compte rendu est dans", espions.messages.success.call_args.args[1])


class FiltrePatientFormulaireTests(SimpleTestCase):
    def filtre(self, donnees=None, villes=("Sfax", "Tunis")):
        return FiltrePatientForm(donnees, villes=villes)

    def appliquer(self, donnees, **kw):
        form = self.filtre(donnees)
        self.assertTrue(form.is_valid(), form.errors)
        liste = ListeFiltrable()
        self.assertIs(form.appliquer(liste, AUJOURDHUI, **kw), liste)
        return liste.filtres

    def test_sans_filtre_rien_n_est_restreint(self):
        self.assertEqual(self.appliquer({}), [])

    def test_chaque_filtre(self):
        cas = (
            ({"sexe": "F"}, {"sexe": "F"}),
            ({"ville": "Tunis"}, {"ville__iexact": "Tunis"}),
            ({"compte": "actif"}, {"user__is_active": True}),
            ({"compte": "desactive"}, {"user__is_active": False}),
            ({"age_min": "30"}, {"date_naissance__lte": datetime.date(1996, 10, 22)}),  # 30 ans révolus ou plus : né le 22/10/1996 au plus tard
            ({"age_max": "40"}, {"date_naissance__gt": datetime.date(1985, 10, 22)}),  # 40 ans au plus : pas encore 41 ans
        )
        for donnees, attendu in cas:
            with self.subTest(donnees=donnees):
                self.assertEqual(self.appliquer(donnees), [((), attendu)])

    def test_la_recherche_porte_sur_cinq_champs(self):
        filtres = self.appliquer({"q": "  amel "})
        (args, kwargs), = filtres
        self.assertEqual((len(args), kwargs, isinstance(args[0], Q), len(args[0].children)), (1, {}, True, 5))
        self.assertIn(("user__last_name__icontains", "amel"), args[0].children)

    def test_allergie_severe(self):
        a, b = ObjectId_(), ObjectId_()
        with mock.patch.object(Allergie.objects, "filter") as filtre:
            filtre.return_value.values_list.return_value = [a, b, a]
            filtres = self.appliquer({"allergie_severe": "on"})
        filtre.assert_called_once_with(gravite="severe", active=True)  # une allergie disparue ne compte pas
        self.assertEqual(filtres, [((), {"pk__in": {a, b}})])

    def test_les_filtres_se_cumulent(self):
        self.assertEqual(len(self.appliquer({"sexe": "H", "ville": "Sfax", "age_min": "18", "age_max": "65", "compte": "actif"})), 5)

    def test_valeurs_refusees(self):
        for donnees, champ in (
            ({"age_min": "50", "age_max": "30"}, "age_max"),
            ({"age_min": "-1"}, "age_min"),
            ({"age_max": "200"}, "age_max"),
            ({"age_min": "abc"}, "age_min"),
            ({"sexe": "X"}, "sexe"),
            ({"ville": "Atlantide"}, "ville"),
            ({"compte": "fantome"}, "compte"),
        ):
            with self.subTest(donnees=donnees):
                self.assertIn(champ, self.filtre(donnees).errors)

    def test_les_villes_proposees_viennent_de_la_liste(self):
        self.assertEqual(self.filtre().fields["ville"].choices, [("", "Toutes"), ("Sfax", "Sfax"), ("Tunis", "Tunis")])

    def test_parametres_actifs_pour_la_pagination_et_l_export(self):
        form = self.filtre({"q": " amel ", "sexe": "F", "age_min": "30", "allergie_severe": "on", "ville": "", "compte": ""})
        self.assertEqual(form.parametres(), {"q": "amel", "sexe": "F", "age_min": "30", "allergie_severe": "on"})
        self.assertEqual(self.filtre({}).parametres(), {})
        self.assertEqual(self.filtre({"age_min": "50", "age_max": "30"}).parametres(), {})  # formulaire invalide : aucun filtre retenu

    def test_il_y_a_n_ans(self):
        self.assertEqual(_il_y_a_ans(datetime.date(2026, 10, 22), 30), datetime.date(1996, 10, 22))
        self.assertEqual(_il_y_a_ans(datetime.date(2024, 2, 29), 1), datetime.date(2023, 2, 28))  # 29 février d'une année non bissextile
        self.assertEqual(_il_y_a_ans(datetime.date(2024, 2, 29), 4), datetime.date(2020, 2, 29))


class PatientsListeBackofficeTests(SimpleTestCase):
    def appeler(self, vue, patients, donnees=None, nom="patients"):
        liste = ListeFiltrable(*patients)
        adresse = "/backoffice/patients/" + ("export/" if nom == "patients_exporter" else "")
        requete = requete_admin(adresse, "get", donnees, nom)
        with mock.patch.object(views, "_villes", return_value=["Sfax", "Tunis"]), mock.patch.object(Patient.objects, "select_related") as lien, \
                mock.patch.object(Triage.objects, "values_list", return_value=[]):
            lien.return_value.order_by.return_value = liste
            reponse = vue(requete)
        return reponse, liste

    def test_adresses(self):
        self.assertEqual(reverse("backoffice:patients_exporter"), "/backoffice/patients/export/")
        self.assertIs(resolve("/backoffice/patients/export/").func, views.patients_exporter)  # pas pris pour la fiche d'un patient « export »
        self.assertEqual(reverse("backoffice:patient_desactiver", args=["abc"]), "/backoffice/patients/abc/desactiver/")
        self.assertEqual(reverse("backoffice:patient_reactiver", args=["abc"]), "/backoffice/patients/abc/reactiver/")
        self.assertIs(resolve("/backoffice/patients/abc/").func, views.patient_detail)

    def test_acces_reserve_aux_administrateurs(self):
        for vue in (views.patients, views.patients_exporter, views.patient_desactiver, views.patient_reactiver):
            with self.subTest(vue=vue.__name__):
                requete = RequestFactory().post("/x/")
                requete.user = utilisateur(role="patient")
                with self.assertRaises(PermissionDenied):
                    vue(requete, "abc") if "patient_" in vue.__name__ else vue(requete)
                requete.user = AnonymousUser()
                reponse = vue(requete, "abc") if "patient_" in vue.__name__ else vue(requete)
                self.assertEqual(reponse.status_code, 302)

    def test_la_liste_s_affiche_avec_ses_filtres(self):
        reponse, liste = self.appeler(views.patients, [un_patient_de_liste(), un_patient_de_liste("Karim", "Jaziri", actif=False)])
        html = reponse.content.decode()
        for texte in ("Nom, e-mail, téléphone ou ville", "Âge minimum", "Âge maximum", "Avec une allergie sévère", 'name="sexe"', 'name="ville"',
                      "Exporter en CSV", "Amel Zouari", "Karim Jaziri", "amel@exemple.tn", 'href="/backoffice/patients/export/"'):
            self.assertIn(texte, html)
        self.assertEqual(html.count("Désactivé</span>"), 1)  # seul le compte désactivé est signalé
        self.assertEqual(liste.filtres, [])

    def test_les_filtres_s_appliquent_et_suivent_l_export_et_la_pagination(self):
        reponse, liste = self.appeler(views.patients, [un_patient_de_liste()], {"sexe": "F", "age_min": "30"})
        self.assertEqual(len(liste.filtres), 2)
        html = reponse.content.decode()
        self.assertIn('href="/backoffice/patients/export/?sexe=F&amp;age_min=30"', html)
        self.assertIn("Réinitialiser", html)

    def test_aucun_resultat(self):
        reponse, _ = self.appeler(views.patients, [], {"sexe": "H"})
        self.assertIn("Aucun patient ne correspond à ces critères.", reponse.content.decode())
        reponse, _ = self.appeler(views.patients, [])
        self.assertIn("Aucun patient inscrit pour le moment.", reponse.content.decode())

    def test_des_filtres_incoherents_sont_signales_sans_rien_filtrer(self):
        reponse, liste = self.appeler(views.patients, [un_patient_de_liste()], {"age_min": "50", "age_max": "30"})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("L&#x27;âge maximum doit être supérieur ou égal à l&#x27;âge minimum.", reponse.content.decode())
        self.assertEqual(liste.filtres, [])

    def test_export_csv(self):
        amel = un_patient_de_liste()
        piege = un_patient_de_liste("Karim", "=cmd|' /C calc'!A0", actif=False, ville="+Sfax")
        reponse, liste = self.appeler(views.patients_exporter, [amel, piege], {"ville": "Tunis"}, "patients_exporter")
        self.assertEqual(reponse["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(reponse["Content-Disposition"], 'attachment; filename="patients-mediconnect.csv"')
        self.assertEqual(len(liste.filtres), 1)  # le même filtre que la liste
        texte = reponse.content.decode("utf-8")
        self.assertTrue(texte.startswith("\ufeff"))  # Excel affiche bien les accents
        lignes = list(csv.reader(io.StringIO(texte.lstrip("\ufeff")), delimiter=";"))
        self.assertEqual(lignes[0], ["Nom", "Prénom", "E-mail", "Téléphone", "Sexe", "Date de naissance", "Âge", "Ville", "Compte", "Inscrit le", "Demandes"])
        self.assertEqual(lignes[1], ["Zouari", "Amel", "amel@exemple.tn", "20111222", "Femme", "04/05/1990", str(amel.age), "Tunis", "actif", "01/09/2026", "0"])
        self.assertEqual((lignes[2][0], lignes[2][7], lignes[2][8]), ("'=cmd|' /C calc'!A0", "'+Sfax", "désactivé"))  # jamais exécuté comme une formule

    def test_la_protection_des_formules_est_partagee(self):
        for texte in ("=1+1", "+1", "-1", "@x"):
            self.assertTrue(proteger_tableur(texte).startswith("'"))
        self.assertEqual(proteger_tableur("Amel"), "Amel")
        self.assertEqual(proteger_tableur(""), "")


class DesactivationPatientBackofficeTests(SimpleTestCase):
    def appeler(self, vue, patient, methode="post"):
        requete = requete_admin(f"/backoffice/patients/{patient.pk}/x/", methode)
        espions = SimpleNamespace(messages=mock.Mock(), desactiver=mock.Mock(return_value=3), reactiver=mock.Mock())
        with mock.patch.object(views, "objet_ou_404", return_value=patient), mock.patch.object(views, "messages", espions.messages), \
                mock.patch.object(views.gestion_compte, "desactiver", espions.desactiver), mock.patch.object(views.gestion_compte, "reactiver", espions.reactiver):
            reponse = vue(requete, str(patient.pk))
        return reponse, espions

    def test_desactiver(self):
        patient = un_patient_de_liste()
        reponse, espions = self.appeler(views.patient_desactiver, patient)
        espions.desactiver.assert_called_once_with(patient.user)
        self.assertEqual((reponse.status_code, reponse["Location"]), (302, f"/backoffice/patients/{patient.pk}/"))
        message = espions.messages.success.call_args.args[1]
        self.assertIn("Amel Zouari", message)
        self.assertIn("3 demande(s) en attente annulée(s)", message)

    def test_deja_desactive(self):
        reponse, espions = self.appeler(views.patient_desactiver, un_patient_de_liste(actif=False))
        espions.desactiver.assert_not_called()
        espions.messages.info.assert_called_once()

    def test_un_compte_du_personnel_ne_se_desactive_pas_ici(self):
        for vue in (views.patient_desactiver, views.patient_reactiver):
            with self.subTest(vue=vue.__name__):
                reponse, espions = self.appeler(vue, un_patient_de_liste(staff=True))
                espions.messages.error.assert_called_once()
                espions.desactiver.assert_not_called()
                espions.reactiver.assert_not_called()

    def test_reactiver(self):
        patient = un_patient_de_liste(actif=False)
        reponse, espions = self.appeler(views.patient_reactiver, patient)
        espions.reactiver.assert_called_once_with(patient.user)
        self.assertEqual(reponse.status_code, 302)
        reponse, espions = self.appeler(views.patient_reactiver, un_patient_de_liste())
        espions.reactiver.assert_not_called()  # déjà actif
        espions.messages.info.assert_called_once()

    def test_uniquement_en_post(self):
        for vue in (views.patient_desactiver, views.patient_reactiver):
            with self.subTest(vue=vue.__name__):
                reponse, espions = self.appeler(vue, un_patient_de_liste(), "get")
                self.assertEqual(reponse.status_code, 405)
                espions.desactiver.assert_not_called()
                espions.reactiver.assert_not_called()


class PatientDetailBackofficeTests(SimpleTestCase):
    def rendre(self, patient, consultations=()):
        analyse = SimpleNamespace(vigilance="calme", resume="Femme de 36 ans.", profil_ia=[], importants=[], attentions=[], completude=100)
        return render_to_string("backoffice/patient_detail.html", {
            "patient": patient, "dossier": None, "allergies": [], "mesures": [], "analyse": analyse, "demandes": [], "consultations": list(consultations),
        }, requete_admin(f"/backoffice/patients/{patient.pk}/", nom="patient_detail"))

    def test_compte_actif_propose_la_desactivation(self):
        patient = un_patient_de_liste()
        html = self.rendre(patient)
        self.assertIn("Actif</span>", html)
        self.assertIn(f'action="/backoffice/patients/{patient.pk}/desactiver/"', html)
        self.assertIn("Désactiver le compte", html)
        self.assertNotIn("Réactiver le compte", html)

    def test_compte_desactive_propose_la_reactivation(self):
        patient = un_patient_de_liste(actif=False)
        html = self.rendre(patient)
        self.assertIn("Désactivé</span>", html)
        self.assertIn(f'action="/backoffice/patients/{patient.pk}/reactiver/"', html)
        self.assertNotIn("Désactiver le compte", html)

    def test_compte_du_personnel(self):
        html = self.rendre(un_patient_de_liste(staff=True))
        self.assertIn("Compte du personnel", html)
        self.assertNotIn("/desactiver/", html)

    def test_consultations_passees(self):
        patient = un_patient_de_liste()
        c = Consultation(patient=patient, medecin_nom="Dr Sara Benali", date=datetime.datetime(2026, 10, 17, 9, 0, tzinfo=TUNIS_), diagnostic="Bronchite",
                         resume="Toux et fièvre.", prescription="Amoxicilline 1 g", recommandations="Repos")
        html = self.rendre(patient, [c])
        for texte in ("Consultations passées", '<span class="count">1</span>', "17/10/2026 · Dr Sara Benali", "Bronchite", "Amoxicilline 1 g", "Repos"):
            self.assertIn(texte, html)
        self.assertIn("Aucune consultation enregistrée.", self.rendre(patient))


# --- Page « Modèle de lecture du texte » ------------------------------------------------------------------------------
from ia import modele as modele_ia  # noqa: E402


def evaluation_factice():
    jeu = {"n": 40, "precision": 0.9, "a_un_niveau_pres": 0.95, "graves_reperes": 1.0, "graves_pris_pour_benins": 0.0, "fausses_alertes": 0.05,
           "reference_toujours_la_meme_reponse": 0.4, "repartition": {"1": 5, "2": 5, "3": 10, "4": 10, "5": 10},
           "matrice": [[5, 0, 0, 0, 0], [0, 5, 0, 0, 0], [0, 1, 8, 1, 0], [0, 0, 1, 8, 1], [0, 0, 0, 1, 9]]}
    return {"graine": 1, "n_entrainement": 6000, "repartition_entrainement": {}, "test_genere": jeu, "test_a_la_main": {**jeu, "n": 39},
            "mots_par_niveau": {str(n): ["poitrine", "serre"] for n in range(1, 6)}}


class ModeleTexteBackofficeTests(SimpleTestCase):
    def appeler(self, donnees=None, evaluation="defaut", lecture=None, methode="get"):
        evaluation = evaluation_factice() if evaluation == "defaut" else evaluation
        requete = requete_admin("/backoffice/modele-texte/", methode, donnees, "modele_texte")
        with mock.patch.object(modele_ia, "charger_evaluation", return_value=evaluation), mock.patch.object(modele_ia, "predire", return_value=lecture), \
                mock.patch.object(views.ReglageTriage, "actuel", return_value=ReglageTriage(seuil_modele=85)):
            return views.modele_texte(requete)

    def test_adresse_et_acces(self):
        self.assertEqual(reverse("backoffice:modele_texte"), "/backoffice/modele-texte/")
        self.assertIs(resolve("/backoffice/modele-texte/").func, views.modele_texte)
        requete = RequestFactory().get("/x/")
        requete.user = utilisateur(role="patient")
        with self.assertRaises(PermissionDenied):
            views.modele_texte(requete)
        requete.user = AnonymousUser()
        self.assertEqual(views.modele_texte(requete).status_code, 302)

    def test_la_page_montre_ses_chiffres_et_ses_limites(self):
        html = self.appeler().content.decode()
        for texte in ("Modèle de lecture du texte", "données synthétiques", "ne peut que relever", "<strong class=\"font-medium text-gray-800\">85 %</strong>",
                      "Phrases générées (test)", "Phrases écrites à la main (contrôle)", "Niveau exact", "90 %", "Cas graves repérés", "100 %", "Fausses alertes", "5 %",
                      "Matrice de confusion", "Les mots qui pèsent le plus", "poitrine · serre", "Réentraîner le modèle", "pas un test indépendant"):
            self.assertIn(texte, html)
        self.assertIn("Essayer une phrase", html)

    def test_matrice_de_confusion_diagonale_mise_en_valeur(self):
        html = self.appeler().content.decode()
        self.assertEqual(html.count('class="diag"'), 10)  # 5 cases par jeu de test, deux jeux

    def test_modele_pas_encore_entraine(self):
        html = self.appeler(evaluation=None).content.decode()
        self.assertIn("n'a pas encore été entraîné", html)
        self.assertIn("entrainer_triage", html)
        self.assertNotIn("Phrases générées (test)", html)

    def test_essai_en_direct(self):
        lecture = {"niveau": 2, "confiance": 0.93, "probas": {"1": 0.03, "2": 0.93, "3": 0.02, "4": 0.01, "5": 0.01}, "mots": ["poitrine", "serre"]}
        html = self.appeler({"texte": "ça me serre la poitrine"}, lecture=lecture).content.decode()
        for texte in ("ça me serre la poitrine", "93 % de confiance", "Mots décisifs : poitrine, serre", "le niveau final serait", "(relevé par le modèle)"):
            self.assertIn(texte, html)
        self.assertEqual(html.count('class="barre-proba"'), 5)

    def test_essai_sans_relevement(self):
        lecture = {"niveau": 5, "confiance": 0.9, "probas": {str(n): 0.2 for n in range(1, 6)}, "mots": []}
        html = self.appeler({"texte": "un petit rhume"}, lecture=lecture).content.decode()
        self.assertIn("le niveau final serait", html)
        self.assertNotIn("relevé par le modèle", html)

    def test_texte_d_essai_limite_et_echappe(self):
        html = self.appeler({"texte": "<script>alert(1)</script>" + "x" * 900}).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertLessEqual(html.count("x" * 100), 5)  # tronqué à 500 caractères

    def test_modele_indisponible_pour_l_essai(self):
        self.assertIn("modèle indisponible", self.appeler({"texte": "j'ai mal"}, lecture=None).content.decode())

    def test_reentrainement(self):
        requete = requete_admin("/backoffice/modele-texte/", "post", {"reentrainer": "1"}, "modele_texte")
        modele_factice = object()
        with mock.patch.object(modele_ia, "entrainer", return_value=(modele_factice, evaluation_factice())) as entrainement, mock.patch.object(modele_ia, "sauvegarder") as sauvegarde, \
                mock.patch.object(modele_ia, "installer") as installation, mock.patch.object(views, "messages") as messages:
            reponse = views.modele_texte(requete)
        entrainement.assert_called_once_with()
        sauvegarde.assert_called_once_with(modele_factice, evaluation_factice())
        installation.assert_called_once_with(modele_factice)  # le nouveau modèle sert tout de suite
        messages.success.assert_called_once()
        self.assertEqual((reponse.status_code, reponse["Location"]), (302, "/backoffice/modele-texte/"))

    def test_lien_depuis_les_parametres(self):
        gabarit = (RACINE / "backoffice" / "templates" / "backoffice" / "parametres.html").read_text(encoding="utf-8")
        self.assertIn("{% url 'backoffice:modele_texte' %}", gabarit)

    def test_le_seuil_est_reglable_dans_les_parametres(self):
        form = ReglageTriageForm({**ReglageTriageFormTests.DONNEES, "seuil_modele": 49})
        self.assertIn("seuil_modele", form.errors)
        self.assertIn("seuil_modele", ReglageTriageForm({**ReglageTriageFormTests.DONNEES, "seuil_modele": 100}).errors)
        self.assertTrue(ReglageTriageForm({**ReglageTriageFormTests.DONNEES, "seuil_modele": 70}).is_valid())

    def test_la_fiche_du_rendez_vous_montre_la_lecture_du_texte(self):
        triage = RendezVousDetailConsultationTests().triage()
        triage.modele_niveau, triage.modele_confiance, triage.modele_mots, triage.modele_releve = 2, 0.93, ["poitrine", "serre"], True
        html = RendezVousDetailConsultationTests().appeler(triage)[0].content.decode()
        for texte in ("Lecture du texte par le modèle", "Niveau estimé 2 (93 % de confiance)", "mots décisifs : poitrine, serre", "niveau relevé"):
            self.assertIn(texte, html)
        sans = RendezVousDetailConsultationTests()
        t2 = sans.triage()
        self.assertNotIn("Lecture du texte par le modèle", sans.appeler(t2)[0].content.decode())
