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
            self.symptome(poids=11, drapeau_rouge=True, niveau_minimal=9).clean_fields(exclude=["patient"])
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
        AutoEvaluation(douleur=5).clean_fields(exclude=["patient"])
        with self.assertRaises(ValidationError):
            AutoEvaluation(douleur=6).clean_fields(exclude=["patient"])

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


# --- CRUD Allergie (relation ForeignKey vers Patient) -----------------------------------
import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

from bson import ObjectId  # noqa: E402
from django.core.exceptions import PermissionDenied  # noqa: E402
from django.template.loader import render_to_string  # noqa: E402
from django.urls import resolve, reverse  # noqa: E402

from . import views as vues_patients  # noqa: E402
from .admin import AllergieInline  # noqa: E402
from .forms import AllergieForm  # noqa: E402
from .models import Allergie  # noqa: E402


def un_patient(naissance=datetime.date(1990, 5, 4)):
    return Patient(pk=ObjectId(), date_naissance=naissance)


def une_allergie(patient=None, **kw):
    valeurs = {"substance": "Pénicilline", "type": "medicament", "gravite": "moderee"}
    valeurs.update(kw)
    return Allergie(patient=patient or un_patient(), **valeurs)


class AllergieModeleTests(SimpleTestCase):
    def setUp(self):
        # Aucun accès à la base : la recherche de doublon est remplacée.
        p = mock.patch.object(Allergie, "_doublon_existe", return_value=False)
        self.doublon = p.start()
        self.addCleanup(p.stop)

    def test_la_relation_est_une_cle_etrangere_vers_le_patient(self):
        champ = Allergie._meta.get_field("patient")
        self.assertTrue(champ.many_to_one)
        self.assertIs(champ.related_model, Patient)
        self.assertEqual(champ.remote_field.related_name, "allergies")

    def test_un_patient_peut_avoir_plusieurs_allergies(self):
        self.assertTrue(Patient._meta.get_field("allergies").one_to_many)

    def test_valeurs_par_defaut(self):
        a = Allergie()
        self.assertEqual((a.type, a.gravite, a.active), ("autre", "moderee", True))

    def test_texte_et_gravite(self):
        a = une_allergie(gravite="severe")
        self.assertEqual(str(a), "Pénicilline (sévère)")
        self.assertTrue(a.est_severe)
        self.assertFalse(une_allergie(gravite="legere").est_severe)

    def test_les_choix_de_type_et_de_gravite(self):
        self.assertEqual([c[0] for c in Allergie.Type.choices], ["medicament", "aliment", "environnement", "autre"])
        self.assertEqual([c[0] for c in Allergie.Gravite.choices], ["legere", "moderee", "severe"])

    def test_gravite_et_type_hors_liste_refuses(self):
        for champ, valeur in (("gravite", "critique"), ("type", "jouet")):
            with self.subTest(champ=champ):
                with self.assertRaises(ValidationError) as ctx:
                    une_allergie(**{champ: valeur}).clean_fields(exclude=["patient"])
                self.assertIn(champ, ctx.exception.message_dict)

    def test_longueurs_maximales(self):
        with self.assertRaises(ValidationError) as ctx:
            une_allergie(substance="x" * 101, reaction="y" * 201).clean_fields(exclude=["patient"])
        self.assertEqual(set(ctx.exception.message_dict), {"substance", "reaction"})

    def test_substance_obligatoire(self):
        with self.assertRaises(ValidationError) as ctx:
            une_allergie(substance="").clean_fields(exclude=["patient"])
        self.assertIn("substance", ctx.exception.message_dict)

    def test_les_espaces_superflus_sont_retires(self):
        a = une_allergie(substance="   Pollen   de   bouleau  ")
        a.clean()
        self.assertEqual(a.substance, "Pollen de bouleau")

    def test_doublon_refuse_sur_la_substance(self):
        self.doublon.return_value = True
        with self.assertRaises(ValidationError) as ctx:
            une_allergie().clean()
        self.assertIn("déjà enregistrée", ctx.exception.message_dict["substance"][0])

    def test_pas_de_doublon_pas_d_erreur(self):
        une_allergie().clean()
        self.doublon.assert_called_once()

    def test_la_recherche_de_doublon_ne_se_fait_pas_sans_substance(self):
        une_allergie(substance="").clean()
        self.doublon.assert_not_called()

    def test_date_dans_le_futur_refusee(self):
        demain = datetime.date.today() + datetime.timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            une_allergie(decouverte_le=demain).clean()
        self.assertIn("futur", ctx.exception.message_dict["decouverte_le"][0])

    def test_date_avant_la_naissance_refusee(self):
        patient = un_patient(naissance=datetime.date(1990, 5, 4))
        with self.assertRaises(ValidationError) as ctx:
            une_allergie(patient=patient, decouverte_le=datetime.date(1989, 12, 31)).clean()
        self.assertIn("naissance", ctx.exception.message_dict["decouverte_le"][0])

    def test_dates_valides_acceptees(self):
        patient = un_patient(naissance=datetime.date(1990, 5, 4))
        for jour in (datetime.date(1990, 5, 4), datetime.date(2015, 3, 1), datetime.date.today()):
            with self.subTest(jour=jour):
                une_allergie(patient=patient, decouverte_le=jour).clean()
        une_allergie(patient=patient, decouverte_le=None).clean()  # la date est facultative


class AllergieFormulaireTests(SimpleTestCase):
    DONNEES = {"substance": "Arachide", "type": "aliment", "gravite": "severe", "reaction": "Urticaire",
               "decouverte_le": "2015-03-01", "active": "on"}

    def setUp(self):
        p = mock.patch.object(Allergie, "_doublon_existe", return_value=False)
        self.doublon = p.start()
        self.addCleanup(p.stop)
        self.patient = un_patient()

    def formulaire(self, donnees=None, **kw):
        return AllergieForm(self.DONNEES if donnees is None else donnees, patient=self.patient, **kw)

    def test_formulaire_valide(self):
        f = self.formulaire()
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["substance"], "Arachide")

    def test_le_patient_n_est_jamais_saisi_donc_jamais_falsifiable(self):
        self.assertEqual(list(AllergieForm.base_fields), ["substance", "type", "gravite", "reaction", "decouverte_le", "active"])
        f = self.formulaire({**self.DONNEES, "patient": str(ObjectId())})
        self.assertTrue(f.is_valid())
        self.assertIs(f.instance.patient, self.patient)  # imposé par la vue

    def test_substance_obligatoire(self):
        f = self.formulaire({**self.DONNEES, "substance": "   "})
        self.assertFalse(f.is_valid())
        self.assertIn("substance", f.errors)

    def test_gravite_obligatoire_et_dans_la_liste(self):
        for valeur in ("", "critique"):
            with self.subTest(valeur=valeur):
                self.assertIn("gravite", self.formulaire({**self.DONNEES, "gravite": valeur}).errors)

    def test_les_regles_du_modele_s_appliquent_au_formulaire(self):
        demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self.assertIn("decouverte_le", self.formulaire({**self.DONNEES, "decouverte_le": demain}).errors)
        self.doublon.return_value = True
        self.assertIn("substance", self.formulaire().errors)

    def test_la_date_est_facultative_et_l_allergie_peut_etre_marquee_disparue(self):
        f = self.formulaire({"substance": "Pollen", "type": "environnement", "gravite": "legere"})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertIsNone(f.cleaned_data["decouverte_le"])
        self.assertFalse(f.cleaned_data["active"])  # case non cochée

    def test_libelles_en_francais_simple(self):
        f = AllergieForm(patient=self.patient)
        self.assertEqual(f.fields["substance"].label, "Allergique à")
        self.assertEqual(f.fields["gravite"].label, "Gravité")
        self.assertEqual([c[1] for c in f.fields["gravite"].choices], ["Légère", "Modérée", "Sévère"])

    def test_choix_de_gravite_masque_mais_accessible_au_clavier(self):
        self.assertEqual(AllergieForm.base_fields["gravite"].widget.attrs.get("class"), "sr-only")
        self.assertEqual(AllergieForm.base_fields["decouverte_le"].widget.input_type, "date")

    def test_le_dossier_ne_gere_plus_les_allergies(self):
        from .forms import DossierMedicalForm

        self.assertNotIn("allergies", DossierMedicalForm.base_fields)
        self.assertEqual(list(DossierMedicalForm.base_fields), ["groupe_sanguin", "antecedents", "traitements_en_cours"])


class AllergieUrlsEtDroitsTests(SimpleTestCase):
    NOMS = ("allergies", "allergie_creer", "allergie_modifier", "allergie_supprimer")

    def test_adresses(self):
        self.assertEqual(reverse("patients:allergies"), "/patients/allergies/")
        self.assertEqual(reverse("patients:allergie_creer"), "/patients/allergies/nouvelle/")
        self.assertEqual(reverse("patients:allergie_modifier", args=["x"]), "/patients/allergies/x/modifier/")
        self.assertEqual(reverse("patients:allergie_supprimer", args=["x"]), "/patients/allergies/x/supprimer/")

    def test_chaque_adresse_pointe_vers_sa_vue(self):
        self.assertIs(resolve("/patients/allergies/").func, vues_patients.allergies)
        self.assertIs(resolve("/patients/allergies/nouvelle/").func, vues_patients.allergie_creer)
        self.assertIs(resolve("/patients/allergies/abc/modifier/").func, vues_patients.allergie_modifier)
        self.assertIs(resolve("/patients/allergies/abc/supprimer/").func, vues_patients.allergie_supprimer)

    def test_visiteur_anonyme_renvoye_vers_la_connexion(self):
        for url in ("/patients/allergies/", "/patients/allergies/nouvelle/",
                    "/patients/allergies/abc/modifier/", "/patients/allergies/abc/supprimer/"):
            with self.subTest(url=url):
                reponse = self.client.get(url)
                self.assertEqual(reponse.status_code, 302)
                self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))

    def test_un_compte_sans_dossier_patient_est_refuse(self):
        requete = RequestFactory().get("/patients/allergies/")
        requete.user = get_user_model()(username="medecin", role="medecin", is_active=True)
        for nom, args in (("allergies", ()), ("allergie_creer", ()), ("allergie_modifier", ("x",)), ("allergie_supprimer", ("x",))):
            with self.subTest(vue=nom):
                with self.assertRaises(PermissionDenied):
                    getattr(vues_patients, nom)(requete, *args)

    def test_les_vues_utilisent_la_recherche_securisee(self):
        # un patient ne peut atteindre que ses propres allergies, et un identifiant invalide donne 404
        import inspect

        for nom in ("allergie_modifier", "allergie_supprimer"):
            source = inspect.getsource(getattr(vues_patients, nom))
            with self.subTest(vue=nom):
                self.assertIn("objet_ou_404(Allergie, pk=pk, patient=patient)", source)


class AllergiePagesTests(SimpleTestCase):
    def requete(self, nom="allergies"):
        requete = RequestFactory().get("/patients/allergies/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="Amine", username="a",
                                       get_full_name=lambda: "Amine Demo")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def allergies(self):
        return [une_allergie(gravite="severe", substance="Arachide"), une_allergie(gravite="legere", substance="Pollen")]

    def rendre_liste(self, actives=None, inactives=None):
        actives = self.allergies() if actives is None else actives
        for i, a in enumerate(actives + (inactives or [])):
            a.pk = ObjectId()
        return render_to_string("patients/allergies.html", {
            "actives": actives, "inactives": inactives or [],
            "severes": [a for a in actives if a.est_severe],
        }, self.requete())

    def test_la_liste_affiche_les_allergies_avec_leur_gravite_ecrite(self):
        html = self.rendre_liste()
        self.assertIn("Arachide", html)
        self.assertIn("sev sev-severe", html)
        self.assertIn(">Sévère<", html)  # la gravité n'est pas indiquée par la couleur seule
        self.assertIn("sev sev-legere", html)

    def test_alerte_en_cas_d_allergie_severe(self):
        html = self.rendre_liste()
        self.assertIn("Allergie sévère enregistrée", html)
        self.assertIn('role="note"', html)
        self.assertNotIn("Allergie sévère enregistrée", self.rendre_liste([une_allergie(gravite="legere")]))

    def test_etat_vide_avec_invitation_a_agir(self):
        html = self.rendre_liste([])
        self.assertIn("Vous n'avez enregistré aucune allergie", html)
        self.assertIn("Ajouter une allergie", html)

    def test_les_allergies_disparues_sont_separees(self):
        disparue = une_allergie(substance="Latex", active=False)
        html = self.rendre_liste(inactives=[disparue])
        self.assertIn("Disparues", html)
        self.assertIn("Latex", html)
        self.assertNotIn("Disparues", self.rendre_liste())

    def test_les_boutons_ont_un_nom_complet_pour_les_lecteurs_d_ecran(self):
        html = self.rendre_liste()
        self.assertIn("Modifier<span class=\"sr-only\"> l'allergie Arachide</span>", html)
        self.assertIn("Supprimer<span class=\"sr-only\"> l'allergie Arachide</span>", html)

    def test_le_menu_contient_les_allergies_et_marque_la_page_courante(self):
        html = self.rendre_liste()
        self.assertIn('href="/patients/allergies/"', html)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn("Allergies</span>", html)

    def test_le_formulaire_s_affiche_en_creation_et_en_modification(self):
        patient = un_patient()
        with mock.patch.object(Allergie, "_doublon_existe", return_value=False):
            creation = render_to_string("patients/allergie_form.html", {
                "form": AllergieForm(patient=patient), "allergie": None}, self.requete("allergie_creer"))
            existante = une_allergie(patient=patient)
            existante.pk = ObjectId()
            edition = render_to_string("patients/allergie_form.html", {
                "form": AllergieForm(instance=existante, patient=patient), "allergie": existante}, self.requete("allergie_modifier"))
        self.assertIn("Ajouter une allergie", creation)
        self.assertIn("Modifier l'allergie", edition)
        for html in (creation, edition):
            self.assertEqual(html.count('type="radio"'), 3)  # trois niveaux de gravité
            self.assertIn("scale-grid-3", html)
            self.assertIn("check-row", html)
            self.assertIn("Annuler", html)
            self.assertIn("csrfmiddlewaretoken", html)

    def test_les_tuiles_de_gravite_vont_du_vert_au_rouge(self):
        with mock.patch.object(Allergie, "_doublon_existe", return_value=False):
            html = render_to_string("patients/allergie_form.html", {
                "form": AllergieForm(patient=un_patient()), "allergie": None}, self.requete("allergie_creer"))
        for classe in ("sc-0", "sc-2", "sc-4"):
            self.assertIn(f"scale-opt {classe}", html)

    def test_erreurs_du_formulaire_annoncees(self):
        with mock.patch.object(Allergie, "_doublon_existe", return_value=False):
            form = AllergieForm({"substance": "", "gravite": "severe", "type": "autre"}, patient=un_patient())
            html = render_to_string("patients/allergie_form.html", {"form": form, "allergie": None}, self.requete("allergie_creer"))
        self.assertIn('role="alert"', html)

    def test_confirmation_de_suppression(self):
        a = une_allergie(gravite="severe")
        a.pk = ObjectId()
        html = render_to_string("patients/allergie_supprimer.html", {"allergie": a}, self.requete("allergie_supprimer"))
        self.assertIn("Supprimer cette allergie ?", html)
        self.assertIn("Oui, supprimer", html)
        self.assertIn("Non, la garder", html)
        self.assertIn("allergie sévère", html)  # mise en garde supplémentaire
        legere = une_allergie(gravite="legere")
        legere.pk = ObjectId()
        self.assertNotIn("allergie sévère", render_to_string("patients/allergie_supprimer.html", {"allergie": legere}, self.requete()))

    def test_les_pages_utilisent_les_composants_existants(self):
        racine = Path(__file__).resolve().parent.parent
        css = (racine / "static" / "css" / "app.css").read_text(encoding="utf-8")
        for classe in (".sev-legere", ".sev-moderee", ".sev-severe", ".scale-grid-3", ".item-row", ".check-row"):
            self.assertIn(classe, css, classe)


class AllergieAdministrationEtCommandesTests(SimpleTestCase):
    def test_allergie_dans_l_administration(self):
        ma = admin.site._registry[Allergie]
        self.assertIn("gravite", ma.list_filter)
        self.assertIn("patient__user__last_name", ma.search_fields)
        self.assertEqual(ma.autocomplete_fields, ("patient",))
        self.assertTrue(ma.list_select_related)

    def test_les_allergies_se_modifient_depuis_la_fiche_patient(self):
        self.assertIn(AllergieInline, admin.site._registry[Patient].inlines)

    def test_les_allergies_de_demonstration_sont_valides(self):
        from .management.commands.charger_demo import ALLERGIES, PATIENTS

        identifiants = {p[0] for p in PATIENTS}
        types = {c[0] for c in Allergie.Type.choices}
        gravites = {c[0] for c in Allergie.Gravite.choices}
        vues = set()
        for ident, substance, type_, gravite, reaction in ALLERGIES:
            with self.subTest(allergie=substance):
                self.assertIn(ident, identifiants)
                self.assertIn(type_, types)
                self.assertIn(gravite, gravites)
                self.assertLessEqual(len(substance), 100)
                self.assertLessEqual(len(reaction), 200)
                self.assertNotIn((ident, substance.lower()), vues)  # pas de doublon
                vues.add((ident, substance.lower()))
        self.assertTrue(any(a[3] == "severe" for a in ALLERGIES))  # un cas sévère pour la démonstration

    def test_la_commande_de_reprise_propose_une_simulation(self):
        from .management.commands.migrer_allergies import Command

        parser = Command().create_parser("manage.py", "migrer_allergies")
        self.assertTrue(parser.parse_args(["--simuler"]).simuler)
        self.assertFalse(parser.parse_args([]).simuler)

    def test_la_commande_de_reprise_utilise_des_valeurs_prudentes(self):
        import inspect

        from .management.commands import migrer_allergies

        source = inspect.getsource(migrer_allergies)
        self.assertIn("Allergie.Gravite.MODEREE", source)  # gravité inconnue : valeur moyenne, modifiable ensuite
        self.assertIn("substance__iexact", source)  # relançable sans doublon

    def test_le_dossier_ne_garde_plus_de_champ_allergies_dans_le_profil(self):
        racine = Path(__file__).resolve().parent.parent
        profil = (racine / "patients" / "templates" / "patients" / "profil.html").read_text(encoding="utf-8")
        self.assertIn("patients:allergies", profil)
        self.assertIn("Gérer mes allergies", profil)
