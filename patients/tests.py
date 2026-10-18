from django.test import SimpleTestCase

from . import medecins_test
from .triage import evaluer


def sym(nom, poids, rouge=False, minimal=None):
    return {"nom": nom, "poids": poids, "drapeau_rouge": rouge, "niveau_minimal": minimal}


class TriageTests(SimpleTestCase):
    def test_aucun_symptome_est_non_urgent(self):
        r = evaluer([])
        self.assertEqual(r.niveau, 5)
        self.assertEqual(r.score, 0)

    def test_symptome_leger(self):
        self.assertEqual(evaluer([sym("toux", 2)]).niveau, 5)

    def test_seuils_de_score(self):
        self.assertEqual(evaluer([sym("a", 5)]).niveau, 4)
        self.assertEqual(evaluer([sym("a", 12)]).niveau, 3)
        self.assertEqual(evaluer([sym("a", 10), sym("b", 10)]).niveau, 2)

    def test_drapeau_rouge_impose_le_niveau_minimal(self):
        r = evaluer([sym("douleur thoracique", 1, rouge=True, minimal=1)])
        self.assertEqual(r.niveau, 1)
        self.assertEqual(r.drapeaux_rouges, ["douleur thoracique"])

    def test_drapeau_rouge_sans_niveau_donne_niveau_2(self):
        self.assertEqual(evaluer([sym("x", 1, rouge=True)]).niveau, 2)

    def test_drapeau_rouge_ne_baisse_jamais_un_score_eleve(self):
        r = evaluer([sym("x", 30, rouge=False), sym("y", 1, rouge=True, minimal=3)])
        self.assertEqual(r.niveau, 2)

    def test_saturation_critique_donne_niveau_1(self):
        r = evaluer([], {"saturation_oxygene": 85})
        self.assertEqual(r.niveau, 1)
        self.assertIn("saturation", r.explication)

    def test_constantes_normales_najoutent_rien(self):
        r = evaluer([], {"temperature": 36.8, "saturation_oxygene": 98,
                         "frequence_cardiaque": 72, "tension_systolique": 120})
        self.assertEqual(r.score, 0)

    def test_valeurs_none_ignorees(self):
        self.assertEqual(evaluer([], {"temperature": None}).score, 0)

    def test_explication_mentionne_niveau_et_score(self):
        r = evaluer([sym("fièvre", 6)])
        self.assertTrue(r.explication.startswith("Niveau 4 (score 6)"))


class MedecinsTestListe(SimpleTestCase):
    def test_trouver(self):
        self.assertEqual(medecins_test.trouver("m1")["nom"], "Dr Sara Benali")
        self.assertIsNone(medecins_test.trouver("inconnu"))

    def test_filtrer(self):
        res = medecins_test.filtrer(specialite="Cardiologie")
        self.assertEqual([m["id"] for m in res], ["m2"])
        self.assertTrue(all(m["ville"] == "Sfax" for m in medecins_test.filtrer(ville="Sfax")))


from .suggestions import choisir_alternatives, est_eligible  # noqa: E402


def med(id_, spec="Médecine générale", ville="Tunis", dispo=True):
    return {"id": id_, "nom": f"Dr {id_}", "specialite": spec, "ville": ville, "disponible": dispo}


class SuggestionsTests(SimpleTestCase):
    def test_seuls_les_niveaux_1_et_2_sont_eligibles(self):
        self.assertTrue(est_eligible(1))
        self.assertTrue(est_eligible(2))
        self.assertFalse(est_eligible(3))
        self.assertFalse(est_eligible(None))

    def test_pas_de_proposition_pour_un_cas_non_tres_urgent(self):
        c = med("a")
        self.assertEqual(choisir_alternatives(3, c, [c, med("b")], {}), [])

    def test_propose_le_medecin_avec_le_moins_de_monde_devant(self):
        c, b, d = med("a"), med("b"), med("d")
        files = {"a": [1, 1, 2], "b": [1], "d": []}
        res = choisir_alternatives(1, c, [c, b, d], files)
        self.assertEqual([m["id"] for m in res], ["d", "b"])

    def test_ignore_les_medecins_indisponibles(self):
        c, b = med("a"), med("b", dispo=False)
        self.assertEqual(choisir_alternatives(1, c, [c, b], {"a": [1, 1]}), [])

    def test_ne_propose_pas_un_medecin_qui_ne_fait_pas_gagner_de_place(self):
        c, b = med("a"), med("b")
        self.assertEqual(choisir_alternatives(1, c, [c, b], {"a": [], "b": []}), [])

    def test_propose_meme_si_courant_indisponible(self):
        c, b = med("a", dispo=False), med("b")
        res = choisir_alternatives(2, c, [c, b], {})
        self.assertEqual([m["id"] for m in res], ["b"])

    def test_un_patient_moins_urgent_ne_compte_pas_devant(self):
        # Niveau 1 : seuls les niveaux 1 passent devant ; les niveaux 4-5 non.
        c, b = med("a"), med("b")
        res = choisir_alternatives(1, c, [c, b], {"a": [1, 1], "b": [5, 5, 4]})
        self.assertEqual(res[0]["id"], "b")
        self.assertEqual(res[0]["devant"], 0)

    def test_departage_par_specialite_puis_ville(self):
        c = med("a", spec="Cardiologie", ville="Tunis")
        autre = med("b", spec="Pédiatrie", ville="Tunis")
        meme = med("d", spec="Cardiologie", ville="Sfax")
        res = choisir_alternatives(1, c, [c, autre, meme], {"a": [1]})
        self.assertEqual([m["id"] for m in res], ["d", "b"])

    def test_limite(self):
        c = med("a")
        autres = [med(x) for x in "bcdef"]
        self.assertEqual(len(choisir_alternatives(1, c, [c] + autres, {"a": [1]}, limite=2)), 2)


# --- Back-office (admin Django) ------------------------------------------------
from types import SimpleNamespace  # noqa: E402

from django.contrib import admin  # noqa: E402
from django.contrib.admin.checks import check_admin_app  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.test import RequestFactory  # noqa: E402

from .admin import DossierMedicalInline  # noqa: E402
from .models import DossierMedical, Patient, Symptome, Triage  # noqa: E402


def requete_admin():
    requete = RequestFactory().get("/admin/")
    requete.user = get_user_model()(
        username="root", is_superuser=True, is_staff=True, is_active=True
    )
    return requete


class SymptomeRegleDrapeauRougeTests(SimpleTestCase):
    def symptome(self, **kw):
        valeurs = {"nom": "Test", "poids": 5, "drapeau_rouge": False, "niveau_minimal": None}
        valeurs.update(kw)
        return Symptome(**valeurs)

    def test_drapeau_rouge_sans_niveau_est_refuse(self):
        with self.assertRaises(ValidationError) as ctx:
            self.symptome(drapeau_rouge=True).clean()
        self.assertIn("niveau_minimal", ctx.exception.message_dict)

    def test_niveau_sans_drapeau_rouge_est_refuse(self):
        with self.assertRaises(ValidationError) as ctx:
            self.symptome(niveau_minimal=2).clean()
        self.assertIn("niveau_minimal", ctx.exception.message_dict)

    def test_cas_valides(self):
        self.symptome().clean()
        self.symptome(drapeau_rouge=True, niveau_minimal=1).clean()

    def test_poids_et_niveau_hors_bornes(self):
        with self.assertRaises(ValidationError) as ctx:
            self.symptome(poids=11, drapeau_rouge=True, niveau_minimal=9).clean_fields()
        self.assertIn("poids", ctx.exception.message_dict)
        self.assertIn("niveau_minimal", ctx.exception.message_dict)

    def test_le_catalogue_de_depart_respecte_la_regle(self):
        from .management.commands.charger_symptomes import SYMPTOMES

        for nom, poids, rouge, minimal in SYMPTOMES:
            with self.subTest(symptome=nom):
                Symptome(nom=nom, poids=poids, drapeau_rouge=rouge, niveau_minimal=minimal).clean()


class TriageAdminTests(SimpleTestCase):
    def setUp(self):
        self.ma = admin.site._registry[Triage]
        self.requete = requete_admin()

    def test_seuls_statut_et_niveau_medecin_sont_modifiables(self):
        formulaire = self.ma.get_form(self.requete, obj=Triage())()
        self.assertEqual(sorted(formulaire.fields), sorted(self.ma.CHAMPS_MODIFIABLES))

    def test_les_champs_sensibles_sont_en_lecture_seule(self):
        sensibles = {
            "patient", "medecin_nom", "medecin_specialite", "niveau", "score",
            "explication", "drapeaux_rouges", "symptomes_declares",
            "auto_evaluation_declaree", "constantes_declarees", "texte_libre", "cree_le",
        }
        self.assertTrue(sensibles <= set(self.ma.get_readonly_fields(self.requete, Triage())))

    def test_on_ne_cree_pas_de_triage_a_la_main(self):
        self.assertFalse(self.ma.has_add_permission(self.requete))

    def test_affichage_lisible_des_symptomes(self):
        obj = SimpleNamespace(symptomes=[
            SimpleNamespace(nom="Toux", drapeau_rouge=False),
            SimpleNamespace(nom="Douleur thoracique", drapeau_rouge=True),
        ])
        self.assertEqual(
            self.ma.symptomes_declares(obj), "Toux, Douleur thoracique (alerte)"
        )
        self.assertEqual(self.ma.symptomes_declares(SimpleNamespace(symptomes=[])), "—")

    def test_affichage_lisible_des_constantes(self):
        c = SimpleNamespace(temperature=38.5, tension_systolique=None, tension_diastolique=None,
                            frequence_cardiaque=None, saturation_oxygene=88)
        texte = self.ma.constantes_declarees(SimpleNamespace(constantes=c))
        self.assertIn("température 38.5 °C", texte)
        self.assertIn("saturation 88 %", texte)
        self.assertEqual(self.ma.constantes_declarees(SimpleNamespace(constantes=None)), "—")

    def test_recherche_et_filtres(self):
        self.assertIn("patient__user__last_name", self.ma.search_fields)
        self.assertIn("medecin_nom", self.ma.search_fields)
        for filtre in ("statut", "niveau", "niveau_medecin", "cree_le"):
            self.assertIn(filtre, self.ma.list_filter)


class PatientEtDossierAdminTests(SimpleTestCase):
    def test_chargement_du_compte_avec_le_patient(self):
        for modele in (Patient, DossierMedical, Triage):
            with self.subTest(modele=modele.__name__):
                self.assertTrue(admin.site._registry[modele].list_select_related)

    def test_compte_choisi_par_recherche(self):
        self.assertEqual(admin.site._registry[Patient].autocomplete_fields, ("user",))
        self.assertEqual(admin.site._registry[DossierMedical].autocomplete_fields, ("patient",))

    def test_dossier_en_inline_dans_patient(self):
        ma = admin.site._registry[Patient]
        self.assertIn(DossierMedicalInline, ma.inlines)
        self.assertEqual(DossierMedicalInline.max_num, 1)
        self.assertFalse(DossierMedicalInline.can_delete)

    def test_recherche_et_filtres_patient(self):
        ma = admin.site._registry[Patient]
        for champ in ("user__last_name", "user__email", "telephone", "ville"):
            self.assertIn(champ, ma.search_fields)
        self.assertIn("sexe", ma.list_filter)
        self.assertIn("groupe_sanguin", admin.site._registry[DossierMedical].list_filter)

    def test_ponderations_modifiables_dans_la_liste(self):
        ma = admin.site._registry[Symptome]
        self.assertEqual(ma.list_editable, ("poids", "actif"))
        self.assertIn("niveau_minimal", ma.list_filter)

    def test_les_controles_d_admin_de_django_passent(self):
        self.assertEqual(check_admin_app(None), [])


# --- Auto-évaluation du patient (échelles de 0 à 5) ------------------------------
from .echelles import ECHELLES, NIVEAU_MAX, choix  # noqa: E402
from .forms import AutoEvaluationForm, SymptomesForm  # noqa: E402
from .models import AutoEvaluation  # noqa: E402
from .triage import POINTS_ECHELLES  # noqa: E402


class EchellesTests(SimpleTestCase):
    def test_chaque_echelle_a_six_niveaux_de_0_a_5(self):
        for nom, echelle in ECHELLES.items():
            with self.subTest(echelle=nom):
                self.assertEqual(len(echelle["niveaux"]), NIVEAU_MAX + 1)
                self.assertEqual([v for v, _ in choix(nom)], [0, 1, 2, 3, 4, 5])
                self.assertTrue(echelle["question"].endswith("?"))

    def test_le_moteur_couvre_toutes_les_valeurs_de_toutes_les_echelles(self):
        self.assertEqual(set(POINTS_ECHELLES), set(ECHELLES))
        for nom, table in POINTS_ECHELLES.items():
            self.assertEqual(sorted(table), [0, 1, 2, 3, 4, 5], nom)

    def test_les_points_ne_diminuent_jamais_quand_l_echelle_monte(self):
        for nom, table in POINTS_ECHELLES.items():
            points = [table[v][0] for v in range(6)]
            self.assertEqual(points, sorted(points), nom)

    def test_le_niveau_minimal_ne_se_relache_jamais_quand_l_echelle_monte(self):
        # Une fois un niveau minimal imposé, une valeur plus forte l'impose aussi
        # et ne peut pas être moins urgente (1 = vital est plus urgent que 3).
        for nom, table in POINTS_ECHELLES.items():
            precedent = None
            for v in range(6):
                minimal = table[v][1]
                if precedent is not None:
                    self.assertIsNotNone(minimal, f"{nom} {v}")
                    self.assertLessEqual(minimal, precedent, f"{nom} {v}")
                if minimal is not None:
                    precedent = minimal


class TriageEchellesTests(SimpleTestCase):
    def test_tout_a_zero_est_non_urgent(self):
        r = evaluer([], None, {"douleur": 0, "fievre": 0, "respiration": 0, "etat_general": 0})
        self.assertEqual((r.score, r.niveau), (0, 5))

    def test_valeurs_graves_imposent_un_niveau(self):
        self.assertEqual(evaluer([], None, {"respiration": 5}).niveau, 1)
        self.assertLessEqual(evaluer([], None, {"douleur": 5}).niveau, 2)
        self.assertLessEqual(evaluer([], None, {"respiration": 3}).niveau, 3)
        self.assertLessEqual(evaluer([], None, {"etat_general": 4}).niveau, 3)

    def test_une_douleur_legere_ne_change_pas_le_niveau(self):
        self.assertEqual(evaluer([], None, {"douleur": 1}).niveau, 5)

    def test_la_temperature_mesuree_remplace_l_echelle_de_fievre(self):
        sans_mesure = evaluer([], None, {"fievre": 4})
        avec_mesure = evaluer([], {"temperature": 36.8}, {"fievre": 4})
        self.assertEqual(sans_mesure.score, 7)
        self.assertEqual(avec_mesure.score, 0)

    def test_l_explication_reprend_les_mots_du_patient(self):
        r = evaluer([], None, {"douleur": 4, "respiration": 5})
        self.assertIn("douleur : très forte (4/5)", r.explication)
        self.assertIn("gêne respiratoire : je suffoque (5/5)", r.explication)

    def test_les_valeurs_absurdes_sont_tolerees(self):
        self.assertEqual(evaluer([], None, {"douleur": "9"}).niveau, 2)  # ramenée à 5
        self.assertEqual(evaluer([], None, {"douleur": "abc"}).score, 0)  # ignorée
        self.assertEqual(evaluer([], None, {"douleur": None}).score, 0)

    def test_cumul_avec_un_drapeau_rouge(self):
        symptomes = [{"nom": "Convulsions", "poids": 9, "drapeau_rouge": True, "niveau_minimal": 2}]
        self.assertEqual(evaluer(symptomes, None, {"respiration": 5}).niveau, 1)

    def test_sans_auto_evaluation_le_comportement_precedent_est_inchange(self):
        self.assertEqual(evaluer([{"nom": "x", "poids": 12}]).niveau, 3)


class AutoEvaluationFormTests(SimpleTestCase):
    def test_valeur_zero_par_defaut(self):
        f = AutoEvaluationForm(data={})
        self.assertTrue(f.is_valid())
        self.assertEqual(f.auto_evaluation(), {n: 0 for n in ECHELLES})

    def test_les_valeurs_sont_des_entiers(self):
        f = AutoEvaluationForm(data={"douleur": "3", "etat_general": "2"})
        self.assertTrue(f.is_valid())
        self.assertEqual(f.auto_evaluation()["douleur"], 3)
        self.assertIsInstance(f.auto_evaluation()["douleur"], int)

    def test_six_est_refuse(self):
        f = AutoEvaluationForm(data={"douleur": "6"})
        self.assertFalse(f.is_valid())
        self.assertIn("douleur", f.errors)

    def test_quatre_questions_dans_l_ordre(self):
        f = AutoEvaluationForm()
        self.assertEqual([b.name for b in f.echelles()], list(ECHELLES))

    def test_plus_de_pouls_ni_de_tension_ni_de_saturation_pour_le_patient(self):
        champs = set(SymptomesForm.base_fields)
        for technique in ("frequence_cardiaque", "tension_systolique", "saturation_oxygene"):
            self.assertNotIn(technique, champs)
        self.assertIn("temperature", champs)
        self.assertEqual(SymptomesForm.CONSTANTES, ("temperature",))

    def test_un_envoi_vide_est_refuse(self):
        f = SymptomesForm(data={})
        self.assertFalse(f.is_valid())
        self.assertTrue(f.non_field_errors())

    def test_une_echelle_au_dessus_de_zero_suffit(self):
        self.assertTrue(SymptomesForm(data={"etat_general": "3"}).is_valid())

    def test_un_texte_seul_suffit(self):
        self.assertTrue(SymptomesForm(data={"texte_libre": "J'ai mal au dos"}).is_valid())

    def test_la_temperature_a_des_bornes(self):
        self.assertFalse(SymptomesForm(data={"etat_general": "3", "temperature": "50"}).is_valid())
        f = SymptomesForm(data={"etat_general": "3", "temperature": "38.5"})
        self.assertTrue(f.is_valid())
        self.assertEqual(float(f.constantes()["temperature"]), 38.5)


class AutoEvaluationStockageTests(SimpleTestCase):
    def test_bornes_du_modele(self):
        AutoEvaluation(douleur=5).clean_fields()
        with self.assertRaises(ValidationError):
            AutoEvaluation(douleur=6).clean_fields()

    def test_resume_lisible(self):
        t = Triage(auto_evaluation=AutoEvaluation(douleur=4, etat_general=2))
        resume = t.auto_evaluation_resume()
        self.assertEqual([e["nom"] for e in resume], ["douleur", "état général"])
        self.assertEqual(resume[0]["libelle"], "Très forte")
        self.assertEqual(resume[1]["valeur"], 2)

    def test_resume_vide(self):
        self.assertEqual(Triage().auto_evaluation_resume(), [])
        self.assertEqual(Triage(auto_evaluation=AutoEvaluation()).auto_evaluation_resume(), [])

    def test_affichage_dans_l_admin(self):
        ma = admin.site._registry[Triage]
        t = Triage(auto_evaluation=AutoEvaluation(respiration=5))
        self.assertEqual(ma.auto_evaluation_declaree(t), "gêne respiratoire : je suffoque (5/5)")
        self.assertEqual(ma.auto_evaluation_declaree(Triage()), "—")
