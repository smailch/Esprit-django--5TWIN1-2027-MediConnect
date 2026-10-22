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

    def test_le_menu_marque_mon_dossier_sur_les_pages_d_allergies(self):
        html = self.rendre_liste()
        self.assertIn('href="/patients/dossier/"', html)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn("Mon dossier</span>", html)

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


# --- CRUD Mesure de santé (relation ForeignKey vers Patient) ----------------------------
from django.utils import timezone  # noqa: E402

from .admin import MesureInline  # noqa: E402
from .forms import MesureForm  # noqa: E402
from .models import Mesure  # noqa: E402

RECHERCHE_DOUBLON_MESURE = Mesure._doublon_existe  # l'original, avant les remplacements des tests


def une_mesure(patient=None, **kw):
    valeurs = {"type": "poids", "valeur": 70, "mesure_le": timezone.now() - datetime.timedelta(hours=2)}
    valeurs.update(kw)
    if valeurs["type"] == "tension" and "valeur2" not in valeurs and valeurs["valeur"] is not None:
        valeurs["valeur2"] = min(valeurs["valeur"] - 1, 80)  # second chiffre cohérent par défaut
    return Mesure(patient=patient or un_patient(), **valeurs)


class MesureModeleTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(Mesure, "_doublon_existe", return_value=False)
        self.doublon = p.start()
        self.addCleanup(p.stop)

    def test_la_relation_est_une_cle_etrangere_vers_le_patient(self):
        champ = Mesure._meta.get_field("patient")
        self.assertTrue(champ.many_to_one)
        self.assertIs(champ.related_model, Patient)
        self.assertTrue(Patient._meta.get_field("mesures").one_to_many)

    def test_les_six_types(self):
        self.assertEqual([c[0] for c in Mesure.Type.choices],
                         ["poids", "tension", "glycemie", "temperature", "frequence", "saturation"])
        self.assertEqual(set(Mesure.REGLES), {c[0] for c in Mesure.Type.choices})

    def test_unite_automatique_selon_le_type(self):
        attendu = {"poids": "kg", "tension": "mmHg", "glycemie": "g/L", "temperature": "°C", "frequence": "bpm", "saturation": "%"}
        for type_, unite in attendu.items():
            with self.subTest(type=type_):
                self.assertEqual(une_mesure(type=type_).unite, unite)

    def test_texte_affiche(self):
        self.assertEqual(une_mesure(type="temperature", valeur=38.5).valeur_affichee, "38.5 °C")
        self.assertEqual(une_mesure(type="poids", valeur=70.0).valeur_affichee, "70 kg")
        self.assertEqual(str(une_mesure(type="tension", valeur=120, valeur2=80)), "Tension artérielle : 120/80 mmHg")
        self.assertEqual(une_mesure(type="tension", valeur=120, valeur2=None).valeur_affichee, "120 mmHg")

    def test_valeurs_plausibles_acceptees(self):
        for type_, valeur in (("poids", 70), ("tension", 120), ("glycemie", 0.9), ("temperature", 37),
                              ("frequence", 72), ("saturation", 97)):
            with self.subTest(type=type_):
                une_mesure(type=type_, valeur=valeur).clean()

    def test_valeurs_improbables_refusees_pour_chaque_type(self):
        for type_, valeur in (("poids", 1), ("poids", 401), ("tension", 49), ("tension", 261),
                              ("glycemie", 0.1), ("glycemie", 7), ("temperature", 29), ("temperature", 46),
                              ("frequence", 19), ("frequence", 251), ("saturation", 49), ("saturation", 101)):
            with self.subTest(type=type_, valeur=valeur):
                with self.assertRaises(ValidationError) as ctx:
                    une_mesure(type=type_, valeur=valeur).clean()
                self.assertIn("improbable", ctx.exception.message_dict["valeur"][0])

    def test_bornes_incluses(self):
        for type_, (unite, mini, maxi, *_) in Mesure.REGLES.items():
            for valeur in (mini, maxi):
                with self.subTest(type=type_, valeur=valeur):
                    une_mesure(type=type_, valeur=valeur).clean()

    def test_date_dans_le_futur_refusee(self):
        with self.assertRaises(ValidationError) as ctx:
            une_mesure(mesure_le=timezone.now() + datetime.timedelta(hours=1)).clean()
        self.assertIn("futur", ctx.exception.message_dict["mesure_le"][0])

    def test_la_date_est_arrondie_a_la_minute(self):
        m = une_mesure(mesure_le=timezone.now().replace(second=42, microsecond=5) - datetime.timedelta(hours=1))
        m.clean()
        self.assertEqual((m.mesure_le.second, m.mesure_le.microsecond), (0, 0))

    def test_deux_mesures_du_meme_type_a_la_meme_minute_refusees(self):
        self.doublon.return_value = True
        with self.assertRaises(ValidationError) as ctx:
            une_mesure().clean()
        self.assertIn("existe déjà", ctx.exception.message_dict["mesure_le"][0])

    def test_pas_de_doublon_pas_d_erreur(self):
        une_mesure().clean()
        self.doublon.assert_called_once()

    def test_la_recherche_de_doublon_garde_le_type_et_la_minute(self):
        # un autre type, ou une autre minute, ne sont pas des doublons : le filtre porte sur les trois champs
        import inspect

        source = inspect.getsource(RECHERCHE_DOUBLON_MESURE)
        for morceau in ("patient=self.patient", "type=self.type", "mesure_le=self.mesure_le", "exclude(pk=self.pk)"):
            self.assertIn(morceau, source)

    def test_type_hors_liste_refuse(self):
        with self.assertRaises(ValidationError) as ctx:
            une_mesure(type="humeur").clean_fields(exclude=["patient"])
        self.assertIn("type", ctx.exception.message_dict)

    def test_valeur_et_date_obligatoires(self):
        with self.assertRaises(ValidationError) as ctx:
            une_mesure(valeur=None, mesure_le=None).clean_fields(exclude=["patient"])
        self.assertEqual(set(ctx.exception.message_dict), {"valeur", "mesure_le"})

    def test_note_limitee_a_200_caracteres(self):
        with self.assertRaises(ValidationError) as ctx:
            une_mesure(note="x" * 201).clean_fields(exclude=["patient"])
        self.assertIn("note", ctx.exception.message_dict)

    def test_reperes_haut_et_bas(self):
        cas = (("tension", 140, "haute"), ("tension", 139, ""), ("tension", 89, "basse"), ("tension", 90, ""),
               ("glycemie", 1.3, "haute"), ("glycemie", 0.6, "basse"), ("glycemie", 0.9, ""),
               ("temperature", 38, "haute"), ("temperature", 35, "basse"), ("temperature", 37, ""),
               ("poids", 200, ""), ("poids", 3, ""))
        for type_, valeur, attendu in cas:
            with self.subTest(type=type_, valeur=valeur):
                self.assertEqual(une_mesure(type=type_, valeur=valeur).alerte, attendu)


class MesureFormulaireTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(Mesure, "_doublon_existe", return_value=False)
        self.doublon = p.start()
        self.addCleanup(p.stop)
        self.patient = un_patient()
        self.hier = (timezone.localtime() - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.donnees = {"type": "poids", "valeur": "70,5".replace(",", "."), "mesure_le": self.hier, "note": "Le matin"}

    def formulaire(self, **changements):
        return MesureForm({**self.donnees, **changements}, patient=self.patient)

    def test_formulaire_valide(self):
        f = self.formulaire()
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["valeur"], 70.5)

    def test_le_patient_n_est_jamais_saisi(self):
        self.assertEqual(list(MesureForm.base_fields), ["type", "valeur", "valeur2", "mesure_le", "note"])
        f = self.formulaire(patient=str(ObjectId()))
        self.assertTrue(f.is_valid())
        self.assertIs(f.instance.patient, self.patient)

    def test_champs_obligatoires(self):
        f = MesureForm({}, patient=self.patient)
        self.assertEqual(set(f.errors), {"type", "valeur", "mesure_le"})  # remarque et second chiffre : facultatifs ici

    def test_valeur_non_numerique_refusee(self):
        self.assertIn("valeur", self.formulaire(valeur="beaucoup").errors)

    def test_les_regles_du_modele_s_appliquent(self):
        self.assertIn("valeur", self.formulaire(type="temperature", valeur="60").errors)
        demain = (timezone.localtime() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertIn("mesure_le", self.formulaire(mesure_le=demain).errors)
        self.doublon.return_value = True
        self.assertIn("mesure_le", self.formulaire().errors)

    def test_champ_date_et_heure_et_valeur_decimale(self):
        self.assertEqual(MesureForm.base_fields["mesure_le"].widget.input_type, "datetime-local")
        self.assertEqual(MesureForm.base_fields["valeur"].widget.attrs.get("step"), "any")

    def test_libelles_en_francais_simple(self):
        f = MesureForm(patient=self.patient)
        self.assertEqual(f.fields["type"].label, "Type de mesure")
        self.assertEqual(f.fields["mesure_le"].label, "Date et heure de la mesure")


class MesureUrlsEtDroitsTests(SimpleTestCase):
    def test_adresses(self):
        self.assertEqual(reverse("patients:mesures"), "/patients/mesures/")
        self.assertEqual(reverse("patients:mesure_creer"), "/patients/mesures/nouvelle/")
        self.assertEqual(reverse("patients:mesure_modifier", args=["x"]), "/patients/mesures/x/modifier/")
        self.assertEqual(reverse("patients:mesure_supprimer", args=["x"]), "/patients/mesures/x/supprimer/")

    def test_chaque_adresse_pointe_vers_sa_vue(self):
        self.assertIs(resolve("/patients/mesures/").func, vues_patients.mesures)
        self.assertIs(resolve("/patients/mesures/nouvelle/").func, vues_patients.mesure_creer)
        self.assertIs(resolve("/patients/mesures/abc/modifier/").func, vues_patients.mesure_modifier)
        self.assertIs(resolve("/patients/mesures/abc/supprimer/").func, vues_patients.mesure_supprimer)

    def test_visiteur_anonyme_renvoye_vers_la_connexion(self):
        for url in ("/patients/mesures/", "/patients/mesures/nouvelle/",
                    "/patients/mesures/abc/modifier/", "/patients/mesures/abc/supprimer/"):
            with self.subTest(url=url):
                reponse = self.client.get(url)
                self.assertEqual(reponse.status_code, 302)
                self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))

    def test_un_compte_sans_dossier_patient_est_refuse(self):
        requete = RequestFactory().get("/patients/mesures/")
        requete.user = get_user_model()(username="medecin", role="medecin", is_active=True)
        for nom, args in (("mesures", ()), ("mesure_creer", ()), ("mesure_modifier", ("x",)), ("mesure_supprimer", ("x",))):
            with self.subTest(vue=nom):
                with self.assertRaises(PermissionDenied):
                    getattr(vues_patients, nom)(requete, *args)

    def test_les_vues_utilisent_la_recherche_securisee(self):
        import inspect

        for nom in ("mesure_modifier", "mesure_supprimer"):
            with self.subTest(vue=nom):
                self.assertIn("objet_ou_404(Mesure, pk=pk, patient=patient)", inspect.getsource(getattr(vues_patients, nom)))


class MesurePagesTests(SimpleTestCase):
    def requete(self, nom="mesures"):
        requete = RequestFactory().get("/patients/mesures/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="Amine", username="a",
                                       get_full_name=lambda: "Amine Demo")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def rendre_liste(self, mesures, type_choisi="", **extra):
        for m in mesures:
            m.pk = ObjectId()
        dernieres = []
        for code, libelle in Mesure.Type.choices:
            dernieres.append({"code": code, "libelle": libelle, "mesure": next((m for m in mesures if m.type == code), None)})
        return render_to_string("patients/mesures.html", {
            "dernieres": dernieres, "historique": mesures, "total": len(mesures),
            "types": Mesure.Type.choices, "type_choisi": type_choisi,
            "periodes": vues_patients.PERIODES, "periode": "tout", "unite": "", **extra,
        }, self.requete())

    def test_la_liste_affiche_valeur_unite_et_date(self):
        html = self.rendre_liste([une_mesure(type="tension", valeur=152, valeur2=96, note="Au repos")])
        self.assertIn("Tension artérielle : 152/96 mmHg", html)
        self.assertIn("Au repos", html)
        self.assertIn("Valeur élevée", html)  # repère écrit, pas seulement une couleur

    def test_aucun_repere_pour_une_valeur_normale(self):
        html = self.rendre_liste([une_mesure(type="tension", valeur=120)])
        self.assertNotIn("Valeur élevée", html)
        self.assertNotIn("Valeur basse", html)

    def test_valeur_basse_signalee(self):
        self.assertIn("Valeur basse", self.rendre_liste([une_mesure(type="glycemie", valeur=0.5)]))

    def test_les_quatre_types_ont_leur_carte_meme_sans_mesure(self):
        html = self.rendre_liste([])
        for libelle in ("Poids", "Tension artérielle", "Glycémie", "Température", "Fréquence cardiaque", "Saturation en oxygène"):
            self.assertIn(libelle, html)
        self.assertEqual(html.count("Aucune mesure."), 6)

    def test_etat_vide_avec_invitation_a_agir(self):
        html = self.rendre_liste([])
        self.assertIn("Aucune mesure enregistrée", html)
        self.assertIn("Ajouter une mesure", html)

    def test_filtre_par_type_marque_le_choix_courant(self):
        html = self.rendre_liste([une_mesure()], type_choisi="poids")
        self.assertIn('?type=poids&amp;periode=tout" class="abtn abtn-primary" aria-current="true"', html)
        self.assertIn("pour ce choix", self.rendre_liste([], type_choisi="poids"))

    def test_le_texte_rappelle_que_ce_n_est_pas_un_diagnostic(self):
        self.assertIn("pas un diagnostic", self.rendre_liste([]))

    def test_boutons_nommes_pour_les_lecteurs_d_ecran(self):
        html = self.rendre_liste([une_mesure(type="poids")])
        self.assertRegex(html, r'Modifier<span class="sr-only"> la mesure de poids du ')
        self.assertRegex(html, r'Supprimer<span class="sr-only"> la mesure de poids du ')

    def test_le_menu_marque_mon_dossier_sur_les_pages_de_mesures(self):
        html = self.rendre_liste([])
        self.assertIn('href="/patients/dossier/"', html)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn("Mon dossier</span>", html)

    def test_le_formulaire_affiche_l_unite_selon_le_type(self):
        from .views import _regles

        with mock.patch.object(Mesure, "_doublon_existe", return_value=False):
            html = render_to_string("patients/mesure_form.html", {
                "form": MesureForm(patient=un_patient()), "mesure": None, "regles": _regles()}, self.requete("mesure_creer"))
        self.assertIn("Ajouter une mesure", html)
        self.assertIn('id="regles-mesures"', html)
        self.assertIn('"unite": "mmHg"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("csrfmiddlewaretoken", html)

    def test_erreurs_du_formulaire_annoncees(self):
        from .views import _regles

        with mock.patch.object(Mesure, "_doublon_existe", return_value=False):
            form = MesureForm({"type": "poids", "valeur": "9000", "mesure_le": "2020-01-01T10:00"}, patient=un_patient())
            html = render_to_string("patients/mesure_form.html", {"form": form, "mesure": None, "regles": _regles()}, self.requete("mesure_creer"))
        self.assertIn("Valeur improbable", html)
        self.assertIn('role="alert"', html)

    def test_confirmation_de_suppression(self):
        m = une_mesure(type="poids", valeur=70)
        m.pk = ObjectId()
        html = render_to_string("patients/mesure_supprimer.html", {"mesure": m}, self.requete("mesure_supprimer"))
        self.assertIn("Supprimer cette mesure ?", html)
        self.assertIn("Poids : 70 kg", html)
        self.assertIn("Oui, supprimer", html)
        self.assertIn("Non, la garder", html)


class MesureAdministrationEtDemoTests(SimpleTestCase):
    def test_mesure_dans_l_administration(self):
        ma = admin.site._registry[Mesure]
        self.assertIn("type", ma.list_filter)
        self.assertEqual(ma.autocomplete_fields, ("patient",))
        self.assertIn(MesureInline, admin.site._registry[Patient].inlines)

    def test_les_mesures_de_demonstration_sont_valides(self):
        from .management.commands.charger_demo import MESURES, PATIENTS

        identifiants = {p[0] for p in PATIENTS}
        for ident, type_, valeur, valeur2, heures, note in MESURES:
            with self.subTest(mesure=(ident, type_, valeur)):
                self.assertIn(ident, identifiants)
                self.assertIn(type_, Mesure.REGLES)
                self.assertTrue(Mesure.REGLES[type_][1] <= valeur <= Mesure.REGLES[type_][2])
                self.assertEqual(valeur2 is not None, type_ == "tension")  # second chiffre : tension uniquement
                if valeur2 is not None:
                    self.assertTrue(Mesure.DIASTOLE[0] <= valeur2 < valeur)
                self.assertGreater(heures, 0)  # jamais dans le futur
                self.assertLessEqual(len(note), 200)
        self.assertTrue(any(Mesure(type=t, valeur=v, valeur2=v2).alerte for _, t, v, v2, _, _ in MESURES))  # un cas à signaler


class MesureTensionEtNouveauxTypesTests(SimpleTestCase):
    def setUp(self):
        p = mock.patch.object(Mesure, "_doublon_existe", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def erreurs(self, **kw):
        with self.assertRaises(ValidationError) as ctx:
            une_mesure(type="tension", **kw).clean()
        return ctx.exception.message_dict

    def test_la_tension_exige_le_second_chiffre(self):
        self.assertIn("second chiffre", self.erreurs(valeur=120, valeur2=None)["valeur2"][0])

    def test_le_second_chiffre_doit_etre_plausible(self):
        for v2 in (29, 151):
            with self.subTest(v2=v2):
                self.assertIn("improbable", self.erreurs(valeur=200, valeur2=v2)["valeur2"][0])
        une_mesure(type="tension", valeur=200, valeur2=30).clean()
        une_mesure(type="tension", valeur=200, valeur2=150).clean()

    def test_le_second_chiffre_doit_etre_plus_petit_que_le_premier(self):
        for v2 in (120, 130):
            with self.subTest(v2=v2):
                self.assertIn("plus petit", self.erreurs(valeur=120, valeur2=v2)["valeur2"][0])

    def test_le_second_chiffre_est_efface_hors_tension(self):
        m = une_mesure(type="poids", valeur=70, valeur2=55)
        m.clean()
        self.assertIsNone(m.valeur2)

    def test_repere_sur_le_second_chiffre(self):
        cas = ((120, 90, "haute"), (120, 89, ""), (120, 59, "basse"), (120, 60, ""), (139, 80, ""), (140, 80, "haute"))
        for v, v2, attendu in cas:
            with self.subTest(v=v, v2=v2):
                self.assertEqual(une_mesure(type="tension", valeur=v, valeur2=v2).alerte, attendu)

    def test_reperes_des_nouveaux_types(self):
        cas = (("frequence", 100, ""), ("frequence", 101, "haute"), ("frequence", 49, "basse"), ("frequence", 50, ""),
               ("saturation", 93, "basse"), ("saturation", 94, ""), ("saturation", 100, ""))
        for type_, valeur, attendu in cas:
            with self.subTest(type=type_, valeur=valeur):
                self.assertEqual(une_mesure(type=type_, valeur=valeur).alerte, attendu)


from . import mesures_stats  # noqa: E402


def pts(*valeurs, v2=None):
    debut = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    return [(debut + datetime.timedelta(days=i), v, (v2[i] if v2 else None)) for i, v in enumerate(valeurs)]


class MesuresStatistiquesTests(SimpleTestCase):
    def test_serie_vide(self):
        self.assertIsNone(mesures_stats.resume([]))

    def test_minimum_maximum_moyenne(self):
        r = mesures_stats.resume([70, 72, 74])
        self.assertEqual((r["min"], r["max"], r["moyenne"], r["nombre"]), (70, 74, 72, 3))

    def test_une_seule_mesure_n_a_pas_de_tendance(self):
        self.assertEqual(mesures_stats.resume([70])["tendance"], "")

    def test_tendance_hausse_baisse_stable(self):
        self.assertEqual(mesures_stats.resume([70, 70, 75])["tendance"], "hausse")
        self.assertEqual(mesures_stats.resume([70, 70, 65])["tendance"], "baisse")
        self.assertEqual(mesures_stats.resume([70, 70, 70.5])["tendance"], "stable")

    def test_pas_de_graphique_avec_moins_de_deux_points(self):
        self.assertIsNone(mesures_stats.graphique([]))
        self.assertIsNone(mesures_stats.graphique(pts(70)))

    def test_les_points_restent_dans_le_cadre(self):
        g = mesures_stats.graphique(pts(60, 90, 75, 120))
        for x, y in g["lignes"][0]["sommets"]:
            self.assertTrue(mesures_stats.MARGE_G <= x <= mesures_stats.LARGEUR - mesures_stats.MARGE_D)
            self.assertTrue(mesures_stats.MARGE_H <= y <= mesures_stats.HAUTEUR - mesures_stats.MARGE_B)

    def test_une_valeur_haute_est_dessinee_plus_haut(self):
        sommets = mesures_stats.graphique(pts(60, 90))["lignes"][0]["sommets"]
        self.assertGreater(sommets[1][0], sommets[0][0])  # le temps avance vers la droite
        self.assertLess(sommets[1][1], sommets[0][1])  # plus grand = plus haut (y plus petit)

    def test_valeurs_identiques_ne_font_pas_planter_le_calcul(self):
        self.assertIsNotNone(mesures_stats.graphique(pts(70, 70, 70)))

    def test_deux_courbes_pour_la_tension(self):
        g = mesures_stats.graphique(pts(120, 130, v2=[80, 85]))
        self.assertEqual(len(g["lignes"]), 2)
        self.assertEqual(len(mesures_stats.graphique(pts(120, 130))["lignes"]), 1)

    def test_zone_de_repere(self):
        self.assertIsNone(mesures_stats.graphique(pts(70, 72))["zone"])
        zone = mesures_stats.graphique(pts(100, 150), bas=90, haut=140)["zone"]
        self.assertGreater(zone["hauteur"], 0)
        self.assertGreaterEqual(zone["y"], mesures_stats.MARGE_H)

    def test_dates_aux_extremites(self):
        g = mesures_stats.graphique(pts(1, 2, 3))
        self.assertEqual((g["premiere_date"].day, g["derniere_date"].day), (1, 3))


class MesuresFiltresEtExportTests(SimpleTestCase):
    def mesures(self):
        maintenant = timezone.now()
        return [une_mesure(type="poids", valeur=70, mesure_le=maintenant - datetime.timedelta(days=1)),
                une_mesure(type="poids", valeur=72, mesure_le=maintenant - datetime.timedelta(days=60)),
                une_mesure(type="glycemie", valeur=0.9, mesure_le=maintenant - datetime.timedelta(days=2))]

    def filtrer(self, **params):
        requete = RequestFactory().get("/patients/mesures/", params)
        with mock.patch.object(Mesure.objects, "filter", return_value=self.mesures()):
            return vues_patients._mesures_filtrees(requete, un_patient())

    def test_par_defaut_tout_est_garde(self):
        _, liste, type_, periode = self.filtrer()
        self.assertEqual((len(liste), type_, periode), (3, "", "tout"))

    def test_filtre_par_type(self):
        _, liste, type_, _ = self.filtrer(type="poids")
        self.assertEqual((len(liste), type_), (2, "poids"))

    def test_filtre_par_periode(self):
        _, liste, _, periode = self.filtrer(type="poids", periode="30")
        self.assertEqual((len(liste), periode), (1, "30"))
        self.assertEqual(len(self.filtrer(periode="90")[1]), 3)

    def test_valeurs_inconnues_ignorees(self):
        _, liste, type_, periode = self.filtrer(type="zzz", periode="999")
        self.assertEqual((len(liste), type_, periode), (3, "", "tout"))

    def test_trie_du_plus_recent_au_plus_ancien(self):
        dates = [m.mesure_le for m in self.filtrer()[1]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def exporter(self, mesures):
        requete = RequestFactory().get("/patients/mesures/export/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True)
        with mock.patch.object(vues_patients, "_patient_connecte", return_value=un_patient()), \
                mock.patch.object(vues_patients, "_mesures_filtrees", return_value=([], mesures, "", "tout")):
            return vues_patients.mesures_exporter(requete)

    def test_export_csv_en_telechargement(self):
        r = self.exporter(self.mesures())
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertTrue(r["Content-Type"].startswith("text/csv"))

    def test_export_lisible_dans_excel(self):
        texte = self.exporter(self.mesures()).content.decode("utf-8")
        self.assertTrue(texte.startswith("\ufeffType;Valeur;Second chiffre (tension);Unité;Date et heure;Remarque"))
        lignes = texte.strip().splitlines()
        self.assertEqual(len(lignes), 4)
        self.assertIn("Poids;70;;kg;", texte)

    def test_export_de_la_tension_avec_ses_deux_chiffres(self):
        texte = self.exporter([une_mesure(type="tension", valeur=120, valeur2=80)]).content.decode("utf-8")
        self.assertIn("Tension artérielle;120;80;mmHg;", texte)

    def test_export_protege_contre_les_formules(self):
        for note in ("=1+1", "+cmd", "-2", "@x"):
            with self.subTest(note=note):
                self.assertTrue(vues_patients._protege_tableur(note).startswith("'"))
        self.assertEqual(vues_patients._protege_tableur("à jeun"), "à jeun")
        texte = self.exporter([une_mesure(note="=HYPERLINK(1)")]).content.decode("utf-8")
        self.assertIn(";'=HYPERLINK(1)", texte)

    def test_export_de_l_anonyme_refuse(self):
        reponse = self.client.get("/patients/mesures/export/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))

    def test_adresse_de_l_export(self):
        self.assertEqual(reverse("patients:mesures_exporter"), "/patients/mesures/export/")
        self.assertIs(resolve("/patients/mesures/export/").func, vues_patients.mesures_exporter)


class MesuresGraphiquePageTests(SimpleTestCase):
    def requete(self):
        requete = RequestFactory().get("/patients/mesures/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="A", username="a",
                                       get_full_name=lambda: "A")
        requete.resolver_match = SimpleNamespace(url_name="mesures")
        return requete

    def page(self, mesures, type_choisi, periode="tout"):
        for m in mesures:
            m.pk = ObjectId()
        chrono = list(reversed(mesures))
        bas, haut = Mesure.REGLES[type_choisi][3:]
        resume2 = mesures_stats.resume([m.valeur2 for m in chrono if m.valeur2 is not None]) if type_choisi == "tension" else None
        contexte = {
            "dernieres": [{"code": c, "libelle": l, "mesure": None} for c, l in Mesure.Type.choices],
            "historique": mesures, "total": len(mesures), "types": Mesure.Type.choices,
            "type_choisi": type_choisi, "periodes": vues_patients.PERIODES, "periode": periode,
            "resume": mesures_stats.resume([m.valeur for m in chrono]), "resume2": resume2,
            "unite": Mesure.REGLES[type_choisi][0],
            "graphique": mesures_stats.graphique([(m.mesure_le, m.valeur, m.valeur2) for m in chrono], bas, haut),
        }
        return render_to_string("patients/mesures.html", contexte, self.requete())

    def serie(self, type_="poids", n=3, **kw):
        maintenant = timezone.now()
        return [une_mesure(type=type_, valeur=70 + i, mesure_le=maintenant - datetime.timedelta(days=i), **kw) for i in range(n)]

    def test_statistiques_et_courbe_affichees(self):
        html = self.page(self.serie(), "poids")
        for texte in ("Évolution", "Plus basse", "Plus haute", "Moyenne (3 mesures)", "Tendance"):
            self.assertIn(texte, html)
        self.assertIn("<polyline", html)
        self.assertEqual(html.count("<polyline"), 1)

    def test_courbe_accessible(self):
        html = self.page(self.serie(), "poids")
        self.assertIn('role="img"', html)
        self.assertIn("aria-label=\"Courbe d'évolution de vos mesures du", html)
        self.assertIn("figcaption", html)

    def test_la_tension_a_deux_courbes_et_une_legende(self):
        html = self.page(self.serie("tension", valeur2=80), "tension")
        self.assertEqual(html.count("<polyline"), 2)
        self.assertIn("Second chiffre", html)
        self.assertIn("Zone de repère", html)

    def test_une_seule_mesure_invite_a_en_ajouter(self):
        html = self.page(self.serie(n=1), "poids")
        self.assertNotIn("<polyline", html)
        self.assertIn("au moins deux mesures", html)

    def test_sans_type_choisi_pas_de_graphique(self):
        html = render_to_string("patients/mesures.html", {
            "dernieres": [], "historique": self.serie(), "total": 3, "types": Mesure.Type.choices, "type_choisi": "",
            "periodes": vues_patients.PERIODES, "periode": "tout", "unite": ""}, self.requete())
        self.assertNotIn("<polyline", html)
        self.assertIn("Choisissez un type de mesure", html)

    def test_boutons_de_periode_et_export(self):
        html = self.page(self.serie(), "poids", periode="30")
        self.assertIn('aria-label="Choisir la période"', html)
        self.assertIn('?type=poids&amp;periode=90"', html)
        self.assertIn('?type=poids&amp;periode=30" class="abtn abtn-primary" aria-current="true"', html)
        self.assertIn("/patients/mesures/export/?type=poids&amp;periode=30", html)

    def test_le_formulaire_n_affiche_le_second_chiffre_que_pour_la_tension(self):
        from .views import _regles

        with mock.patch.object(Mesure, "_doublon_existe", return_value=False):
            html = render_to_string("patients/mesure_form.html", {
                "form": MesureForm(patient=un_patient()), "mesure": None, "regles": _regles()}, self.requete())
        self.assertIn('id="bloc-valeur2"', html)
        self.assertIn('bloc2.hidden = type.value !== "tension"', html)
        self.assertIn("Second chiffre de la tension", html)

    def test_les_coordonnees_du_graphique_gardent_le_point_decimal(self):
        # en français Django écrit « 12,5 » : dans un attribut SVG, la virgule rendrait la valeur invalide
        import re

        from django.utils import translation

        with translation.override("fr"):
            html = self.page(self.serie("tension", n=4, valeur2=80), "tension")
        svg = html[html.index("<svg"):html.index("</svg>")]
        self.assertIsNone(re.search(r'(cx|cy|x|y|width|height)="[0-9]+,[0-9]', svg))
        self.assertRegex(svg, r'<circle class="chart-dot-1" cx="[0-9]+(\.[0-9]+)?" cy="[0-9]+(\.[0-9]+)?"')
        self.assertIn('class="chart-zone"', svg)


# --- Dossier médical : synthèse pour le médecin -----------------------------------------
from . import dossier as synthese_dossier  # noqa: E402


def un_dossier(**kw):
    valeurs = {"groupe_sanguin": "A+", "antecedents": "Asthme chronique", "traitements_en_cours": "Ventoline"}
    valeurs.update(kw)
    return DossierMedical(**valeurs)


def un_patient_complet(**kw):
    p = un_patient()
    p.sexe = "F"
    p.contact_urgence_nom, p.contact_urgence_tel = "Sami Trabelsi", "20111222"
    for cle, valeur in kw.items():
        setattr(p, cle, valeur)
    return p


class DossierLogiqueTests(SimpleTestCase):
    def test_dossier_complet_rien_a_completer(self):
        self.assertEqual(synthese_dossier.elements_manquants(un_patient_complet(), un_dossier()), [])

    def test_chaque_information_manquante_est_signalee(self):
        patient, dossier = un_patient_complet(), un_dossier()
        cas = (
            (patient, un_dossier(groupe_sanguin=""), "Groupe sanguin"),
            (patient, un_dossier(antecedents=""), "Antécédents médicaux"),
            (patient, un_dossier(traitements_en_cours="  "), "Traitements en cours"),
            (un_patient_complet(contact_urgence_nom=""), dossier, "Contact en cas d'urgence"),
            (un_patient_complet(contact_urgence_tel=""), dossier, "Contact en cas d'urgence"),
        )
        for p, d, attendu in cas:
            with self.subTest(attendu=attendu):
                self.assertEqual(synthese_dossier.elements_manquants(p, d), [attendu])

    def test_sans_dossier_tout_est_a_completer_sauf_le_contact(self):
        self.assertEqual(synthese_dossier.elements_manquants(un_patient_complet(), None),
                         ["Groupe sanguin", "Antécédents médicaux", "Traitements en cours"])

    def test_derniere_mesure_par_type(self):
        maintenant = timezone.now()
        vieille = une_mesure(type="poids", valeur=80, mesure_le=maintenant - datetime.timedelta(days=9))
        recente = une_mesure(type="poids", valeur=78, mesure_le=maintenant - datetime.timedelta(days=1))
        glycemie = une_mesure(type="glycemie", valeur=0.9, mesure_le=maintenant - datetime.timedelta(days=5))
        res = synthese_dossier.derniere_mesure_par_type([vieille, glycemie, recente])
        self.assertEqual(len(res), 2)
        self.assertIn(recente, res)
        self.assertNotIn(vieille, res)
        self.assertEqual(synthese_dossier.derniere_mesure_par_type([]), [])

    def test_age_calcule_a_partir_de_la_date_de_naissance(self):
        aujourdhui = timezone.localdate()
        cas = ((aujourdhui.replace(year=aujourdhui.year - 30), 30),
               (aujourdhui.replace(year=aujourdhui.year - 30) + datetime.timedelta(days=1), 29))
        for naissance, attendu in cas:
            with self.subTest(naissance=naissance):
                self.assertEqual(Patient(date_naissance=naissance).age, attendu)


class DossierPageTests(SimpleTestCase):
    def requete(self, nom="dossier"):
        requete = RequestFactory().get("/patients/dossier/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="A", username="a",
                                       get_full_name=lambda: "A")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def page(self, patient=None, dossier="defaut", allergies=(), mesures=(), demande=None, manquants=(), analyse=None):
        patient = patient or un_patient_complet()
        allergies = list(allergies)
        for a in allergies:
            a.pk = ObjectId()
        for m in mesures:
            m.pk = ObjectId()
        return render_to_string("patients/dossier.html", {
            "patient": patient, "dossier": un_dossier() if dossier == "defaut" else dossier,
            "allergies": allergies, "severes": [a for a in allergies if a.est_severe], "mesures": list(mesures),
            "derniere_demande": demande, "manquants": list(manquants), "analyse": analyse or analyser_cas()}, self.requete())

    def test_adresse_et_vue(self):
        self.assertEqual(reverse("patients:dossier"), "/patients/dossier/")
        self.assertIs(resolve("/patients/dossier/").func, vues_patients.dossier)

    def test_acces_reserve_aux_patients_connectes(self):
        reponse = self.client.get("/patients/dossier/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))
        requete = RequestFactory().get("/patients/dossier/")
        requete.user = get_user_model()(username="medecin", role="medecin", is_active=True)
        with self.assertRaises(PermissionDenied):
            vues_patients.dossier(requete)

    def test_resume_des_informations_essentielles(self):
        html = self.page()
        for texte in ("Mon dossier médical", "ans", "Femme", "A+", "Sami Trabelsi", "20111222",
                      "Asthme chronique", "Ventoline", "Antécédents médicaux", "Traitements en cours"):
            self.assertIn(texte, html)

    def test_allergies_avec_gravite_ecrite_et_alerte_si_severe(self):
        html = self.page(allergies=[une_allergie(substance="Arachide", gravite="severe", reaction="Urticaire")])
        self.assertIn("Arachide", html)
        self.assertIn(">Sévère<", html)
        self.assertIn("Allergie sévère :", html)
        self.assertIn('role="note"', html)
        self.assertNotIn("Allergie sévère :", self.page(allergies=[une_allergie(gravite="legere")]))

    def test_sections_vides_expliquees(self):
        html = self.page(dossier=un_dossier(antecedents="", traitements_en_cours="", groupe_sanguin=""))
        self.assertIn("Aucune allergie enregistrée.", html)
        self.assertIn("Aucune mesure enregistrée.", html)
        self.assertEqual(html.count("Non renseigné."), 2)
        self.assertIn("Vous n'avez pas encore demandé de consultation.", html)

    def test_page_sans_dossier_ne_plante_pas(self):
        html = self.page(dossier=None)
        self.assertIn("Non renseigné.", html)

    def test_mesures_recentes_avec_repere(self):
        html = self.page(mesures=[une_mesure(type="tension", valeur=152, valeur2=96), une_mesure(type="poids", valeur=70)])
        self.assertIn("Tension artérielle : 152/96 mmHg", html)
        self.assertIn("Poids : 70 kg", html)
        self.assertEqual(html.count("Élevée"), 1)

    def test_derniere_demande_affichee(self):
        demande = SimpleNamespace(medecin_nom="Dr Ben Salah", cree_le=timezone.now(), get_statut_display=lambda: "En attente",
                                  symptomes=[SimpleNamespace(nom="Toux"), SimpleNamespace(nom="Fatigue")], niveau_effectif=3)
        html = self.page(demande=demande)
        for texte in ("Dr Ben Salah", "Toux, Fatigue", "urgence 3 sur 5", "en attente"):
            self.assertIn(texte, html)

    def test_bloc_a_completer_seulement_si_necessaire(self):
        self.assertNotIn("À compléter", self.page())
        html = self.page(manquants=["Groupe sanguin", "Traitements en cours"])
        self.assertIn("À compléter", html)
        self.assertIn("<li>Groupe sanguin</li>", html)
        self.assertIn("Compléter mon dossier", html)

    def test_liens_vers_les_details_et_la_modification(self):
        html = self.page()
        for lien in ('href="/patients/allergies/"', 'href="/patients/mesures/"', 'href="/patients/profil/"'):
            self.assertIn(lien, html)

    def test_page_pas_trop_chargee_quatre_blocs_et_deux_sections(self):
        html = self.page(manquants=["Groupe sanguin"], demande=None)
        self.assertEqual(html.count('class="panel panel-pad'), 4 + 3)  # 4 blocs, analyse, dernière demande, à compléter
        self.assertEqual(html.count("<h1"), 1)

    def test_le_menu_a_quatre_entrees_dont_mon_dossier(self):
        html = self.page()
        self.assertEqual(html.count('aria-current="page"'), 1)
        for lien in ('href="/patients/dossier/"', 'href="/patients/profil/"'):
            self.assertIn(lien, html)
        self.assertNotIn("Allergies</span>", html)  # regroupées sous « Mon dossier »
        self.assertNotIn("Mes mesures</span>", html)

    def test_liens_d_aide_nommes_pour_les_lecteurs_d_ecran(self):
        html = self.page()
        self.assertIn('Gérer<span class="sr-only"> mes allergies</span>', html)
        self.assertIn('Voir tout<span class="sr-only"> l\'historique des mesures</span>', html)


# --- Créneaux de rendez-vous ----------------------------------------------------------------
import zoneinfo  # noqa: E402

from . import planning  # noqa: E402

TUNIS = zoneinfo.ZoneInfo("Africa/Tunis")
LUNDI_8H = datetime.datetime(2026, 10, 19, 8, 0, tzinfo=TUNIS)  # un lundi
SEMAINE = {j: [(9, 12), (14, 17)] for j in range(5)}


class PlanningGenerationTests(SimpleTestCase):
    def test_creneaux_de_30_minutes_dans_les_plages(self):
        libres = planning.generer({0: [(9, 11)]}, LUNDI_8H - datetime.timedelta(days=1))
        heures = [c.strftime("%H:%M") for c in libres if c.date() == LUNDI_8H.date()]
        self.assertEqual(heures, ["09:00", "09:30", "10:00", "10:30"])

    def test_le_dernier_creneau_finit_avant_la_fin_de_la_plage(self):
        libres = planning.generer({0: [(9, 10)]}, LUNDI_8H - datetime.timedelta(days=1))
        self.assertEqual([c.strftime("%H:%M") for c in libres][:2], ["09:00", "09:30"])

    def test_delai_minimum_de_deux_heures(self):
        libres = planning.generer({0: [(9, 12)]}, LUNDI_8H)  # il est 8 h : premier créneau possible à 10 h
        self.assertEqual(libres[0].strftime("%H:%M"), "10:00")
        self.assertTrue(all(c >= LUNDI_8H + datetime.timedelta(hours=2) for c in libres))

    def test_rien_dans_le_passe(self):
        tard = LUNDI_8H.replace(hour=16)
        libres = planning.generer(SEMAINE, tard)
        self.assertTrue(all(c > tard for c in libres))

    def test_horizon_de_quatorze_jours(self):
        libres = planning.generer(SEMAINE, LUNDI_8H)
        self.assertEqual(planning.HORIZON_JOURS, 14)
        self.assertLessEqual(max(libres), LUNDI_8H + datetime.timedelta(days=15))  # jamais au-delà de deux semaines
        self.assertGreater(len(libres), 40)

    def test_jours_sans_horaire_ignores(self):
        libres = planning.generer(SEMAINE, LUNDI_8H)
        self.assertTrue(all(c.weekday() < 5 for c in libres))  # ni samedi ni dimanche

    def test_creneaux_pris_exclus(self):
        pris = [LUNDI_8H.replace(hour=10)]
        libres = planning.generer({0: [(9, 12)]}, LUNDI_8H, pris)
        self.assertNotIn(LUNDI_8H.replace(hour=10), libres)
        self.assertIn(LUNDI_8H.replace(hour=10, minute=30), libres)

    def test_un_creneau_pris_en_heure_utc_est_reconnu(self):
        pris = [LUNDI_8H.replace(hour=10).astimezone(datetime.timezone.utc)]  # la base renvoie de l'UTC
        self.assertNotIn(LUNDI_8H.replace(hour=10), planning.generer({0: [(9, 12)]}, LUNDI_8H, pris))

    def test_ordre_chronologique(self):
        libres = planning.generer(SEMAINE, LUNDI_8H)
        self.assertEqual(libres, sorted(libres))

    def test_medecin_sans_horaire_aucun_creneau(self):
        self.assertEqual(planning.generer({}, LUNDI_8H), [])


class PlanningReglesTests(SimpleTestCase):
    def test_reservable_seulement_en_attente_niveaux_3_a_5(self):
        for niveau, attendu in ((1, False), (2, False), (3, True), (4, True), (5, True), (None, False)):
            with self.subTest(niveau=niveau):
                self.assertEqual(planning.reservable("en_attente", niveau), attendu)
        for statut in ("en_consultation", "termine", "annule"):
            with self.subTest(statut=statut):
                self.assertFalse(planning.reservable(statut, 4))

    def test_lecture_du_choix(self):
        c = planning.lire_choix("2026-10-20T09:30:00+01:00", TUNIS)
        self.assertEqual((c.hour, c.minute), (9, 30))
        self.assertEqual(planning.lire_choix("2026-10-20T09:30", TUNIS).tzinfo, TUNIS)
        for mauvais in ("", "n'importe quoi", "2026-13-45T99:99", None):
            with self.subTest(mauvais=mauvais):
                self.assertIsNone(planning.lire_choix(mauvais, TUNIS))

    def test_moment_de_la_journee(self):
        h = lambda n: LUNDI_8H.replace(hour=n)
        self.assertEqual([planning.periode(h(n)) for n in (8, 11, 12, 17, 18, 20)],
                         ["Matin", "Matin", "Après-midi", "Après-midi", "Soir", "Soir"])

    def test_regroupement_par_jour_et_moment(self):
        libres = planning.generer(SEMAINE, LUNDI_8H - datetime.timedelta(days=1))
        jours = planning.grouper(libres)
        premier = jours[0]
        self.assertEqual(premier["jour"], LUNDI_8H.date())
        self.assertEqual([g["nom"] for g in premier["groupes"]], ["Matin", "Après-midi"])
        self.assertEqual(premier["total"], sum(len(g["creneaux"]) for g in premier["groupes"]))
        self.assertEqual([j["jour"] for j in jours], sorted({c.date() for c in libres}))

    def test_regroupement_vide(self):
        self.assertEqual(planning.grouper([]), [])

    def test_les_horaires_des_medecins_sont_valides(self):
        for m in medecins_test.tous():
            with self.subTest(medecin=m["id"]):
                self.assertIn("horaires", m)
                if not m["disponible"]:
                    self.assertEqual(m["horaires"], {})
                for jour, plages in m["horaires"].items():
                    self.assertIn(jour, range(7))
                    for debut, fin in plages:
                        self.assertTrue(0 <= debut < fin <= 24)

    def test_un_medecin_disponible_a_des_creneaux(self):
        for m in medecins_test.tous():
            if m["disponible"]:
                with self.subTest(medecin=m["id"]):
                    self.assertTrue(planning.generer(m["horaires"], LUNDI_8H))


class TriageCreneauModeleTests(SimpleTestCase):
    def test_champ_facultatif(self):
        champ = Triage._meta.get_field("creneau")
        self.assertTrue(champ.null and champ.blank)

    def test_creneaux_pris_ignorent_les_demandes_inactives_et_la_demande_courante(self):
        a, b = Triage(medecin_id="m1", creneau=LUNDI_8H), Triage(medecin_id="m1", creneau=LUNDI_8H.replace(hour=9))
        sans = Triage(medecin_id="m1", creneau=None)
        a.pk, b.pk, sans.pk = ObjectId(), ObjectId(), ObjectId()
        with mock.patch.object(Triage.objects, "filter", return_value=[a, b, sans]) as f:
            self.assertEqual(Triage.creneaux_pris("m1"), [LUNDI_8H, LUNDI_8H.replace(hour=9)])
            self.assertEqual(Triage.creneaux_pris("m1", exclure_pk=a.pk), [LUNDI_8H.replace(hour=9)])
        statuts = f.call_args.kwargs["statut__in"]
        self.assertEqual(set(statuts), {"en_attente", "en_consultation"})  # annulé et terminé libèrent le créneau


class CreneauxPagesTests(SimpleTestCase):
    def requete(self):
        requete = RequestFactory().get("/patients/triage/x/creneaux/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="A", username="a",
                                       get_full_name=lambda: "A")
        requete.resolver_match = SimpleNamespace(url_name="creneaux")
        return requete

    def triage(self, **kw):
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr Sara Benali", medecin_specialite="Médecine générale",
                   niveau=4, statut="en_attente", explication="x", **kw)
        t.pk = ObjectId()
        return t

    def test_adresses_et_vues(self):
        self.assertEqual(reverse("patients:creneaux", args=["x"]), "/patients/triage/x/creneaux/")
        self.assertEqual(reverse("patients:creneau_retirer", args=["x"]), "/patients/triage/x/creneau/retirer/")
        self.assertIs(resolve("/patients/triage/abc/creneaux/").func, vues_patients.creneaux)
        self.assertIs(resolve("/patients/triage/abc/creneau/retirer/").func, vues_patients.creneau_retirer)

    def test_acces_reserve_aux_patients_connectes(self):
        for url in ("/patients/triage/abc/creneaux/", "/patients/triage/abc/creneau/retirer/"):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r["Location"].startswith("/comptes/connexion/"))
        requete = RequestFactory().get("/x/")
        requete.user = get_user_model()(username="medecin", role="medecin", is_active=True)
        with self.assertRaises(PermissionDenied):
            vues_patients.creneaux(requete, "x")

    def test_les_vues_utilisent_la_recherche_securisee(self):
        import inspect

        for nom in ("creneaux", "creneau_retirer"):
            self.assertIn("objet_ou_404(Triage, pk=pk, patient=patient)", inspect.getsource(getattr(vues_patients, nom)))

    def test_le_retrait_n_accepte_que_post(self):
        import inspect

        requete = RequestFactory().get("/patients/triage/x/creneau/retirer/")
        requete.user = SimpleNamespace(is_authenticated=True)
        reponse = vues_patients.creneau_retirer(requete, "x")  # un simple GET ne doit rien modifier
        self.assertEqual(reponse.status_code, 405)

    def test_la_validation_se_fait_cote_serveur(self):
        import inspect

        source = inspect.getsource(vues_patients.creneaux)
        for morceau in ("choix not in disponibles", "planning.reservable", "Triage.creneaux_pris", "_demandes_actives(patient)",
                        "Second verrou"):
            self.assertIn(morceau, source)

    def rendre(self, triage, jours):
        total = sum(j["total"] for j in jours)
        return render_to_string("patients/creneaux.html", {"triage": triage, "medecin": {}, "jours": jours,
                                                           "total": total, "duree": 30}, self.requete())

    def test_page_avec_creneaux_groupes_par_jour(self):
        jours = planning.grouper_grille(planning.grille(SEMAINE, LUNDI_8H))[:3]
        html = self.rendre(self.triage(), jours)
        self.assertIn("Choisir un créneau", html)
        self.assertEqual(html.count('type="radio" name="debut"'), sum(j["total"] for j in jours))
        self.assertEqual(html.count("<details"), 3)
        self.assertIn("<details class=\"panel\" open>", html)  # seul le premier jour est ouvert
        self.assertIn("Matin", html)
        self.assertIn("Réserver ce créneau", html)
        self.assertIn("csrfmiddlewaretoken", html)
        self.assertIn("consultations de 30 minutes", html)
        self.assertIn("required", html)

    def test_valeur_envoyee_lisible_par_le_serveur(self):
        jours = planning.grouper_grille(planning.grille(SEMAINE, LUNDI_8H))[:1]
        html = self.rendre(self.triage(), jours)
        import re

        valeur = re.search(r'name="debut" value="([^"]+)"', html).group(1)
        self.assertIsNotNone(planning.lire_choix(valeur, TUNIS))
        self.assertEqual(planning.lire_choix(valeur, TUNIS), planning.generer(SEMAINE, LUNDI_8H)[0])

    def test_aucun_creneau_message_clair(self):
        html = self.rendre(self.triage(), [])
        self.assertIn("Aucun créneau disponible", html)
        self.assertNotIn('type="radio"', html)
        self.assertIn("dans l'ordre d'arrivée", html)

    def test_creneau_actuel_rappele(self):
        html = self.rendre(self.triage(creneau=LUNDI_8H.replace(hour=10)), [])
        self.assertIn("Votre créneau actuel", html)
        self.assertIn("10:00", html)

    def rendre_resultat(self, triage, can_book):
        return render_to_string("patients/resultat.html", {"triage": triage, "message": "m", "propositions": [],
                                                           "can_book": can_book}, self.requete())

    def test_resultat_propose_de_choisir_un_creneau(self):
        t = self.triage()
        self.assertIn("Choisir un créneau", self.rendre_resultat(t, True))
        self.assertIn(f"/patients/triage/{t.pk}/creneaux/", self.rendre_resultat(t, True))

    def test_resultat_cas_prioritaire_sans_creneau(self):
        t = self.triage()
        t.niveau = 2
        html = self.rendre_resultat(t, False)
        self.assertIn("pris en charge en priorité", html)
        self.assertNotIn("Choisir un créneau", html)

    def test_resultat_avec_creneau_reserve(self):
        t = self.triage(creneau=LUNDI_8H.replace(hour=10))
        html = self.rendre_resultat(t, True)
        self.assertIn("Changer de créneau", html)
        self.assertIn("Retirer le créneau", html)
        self.assertIn("à 10:00", html)
        self.assertIn("/creneau/retirer/", html)
        self.assertNotIn("Choisir un créneau", html)

    def test_resultat_demande_terminee_pas_de_boutons(self):
        t = self.triage(creneau=LUNDI_8H.replace(hour=10))
        t.statut = "termine"
        html = self.rendre_resultat(t, False)
        self.assertIn("à 10:00", html)
        self.assertNotIn("Changer de créneau", html)

    def test_dossier_et_back_office_montrent_le_creneau(self):
        racine = Path(__file__).resolve().parent.parent
        for fichier in ("patients/templates/patients/dossier.html", "patients/templates/patients/tableau_de_bord.html",
                        "backoffice/templates/backoffice/rendez_vous_detail.html"):
            with self.subTest(fichier=fichier):
                self.assertIn("creneau", (racine / fichier).read_text(encoding="utf-8"))

    def test_styles_des_creneaux_presents(self):
        css = (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")
        for classe in (".slot-day", ".slot-grid", ".slot input:checked + span", ".slot input:focus-visible + span"):
            self.assertIn(classe, css)


# --- Le créneau est une étape du parcours ------------------------------------------------------
class ParcoursCreneauTests(SimpleTestCase):
    def requete(self, nom="creneaux"):
        requete = RequestFactory().get("/x/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="A", username="a",
                                       get_full_name=lambda: "A")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def etapes(self, etape):
        return render_to_string("patients/_etapes.html", {"etape": etape})

    def test_quatre_etapes_dans_l_ordre(self):
        html = self.etapes(1)
        import re

        self.assertEqual(re.findall(r"<span>([^<]+)</span>\s*</li>", html), ["Médecin", "Symptômes", "Créneau", "Résultat"])

    def test_etape_courante_et_etapes_terminees(self):
        for etape in (1, 2, 3, 4):
            with self.subTest(etape=etape):
                html = self.etapes(etape)
                self.assertEqual(html.count('aria-current="step"'), 1)
                self.assertEqual(html.count("step-done"), etape - 1)
                self.assertEqual(html.count("step-current"), 1)

    def test_l_etape_creneau_est_la_troisieme(self):
        html = self.etapes(3)
        self.assertEqual(html.count("✓"), 2)
        self.assertRegex(html, r'aria-current="step">\s*<span class="step-dot">3</span><span>Créneau</span>')

    def test_chaque_page_du_parcours_declare_sa_place(self):
        racine = Path(__file__).resolve().parent / "templates" / "patients"
        attendu = {"medecins.html": 1, "symptomes.html": 2, "creneaux.html": 3, "resultat.html": 4}
        for fichier, etape in attendu.items():
            with self.subTest(fichier=fichier):
                self.assertIn(f"with etape={etape}", (racine / fichier).read_text(encoding="utf-8"))

    def test_la_page_des_creneaux_montre_la_barre_d_etapes(self):
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr X", niveau=4, statut="en_attente")
        t.pk = ObjectId()
        html = render_to_string("patients/creneaux.html", {"triage": t, "medecin": {}, "jours": [], "total": 0, "duree": 30}, self.requete())
        self.assertIn('class="stepper"', html)
        self.assertIn("Passer : rester dans la file", render_to_string("patients/creneaux.html", {
            "triage": t, "medecin": {}, "jours": planning.grouper_grille(planning.grille(SEMAINE, LUNDI_8H))[:1], "total": 5, "duree": 30}, self.requete()))

    def soumettre_symptomes(self, niveau):
        """Envoie le formulaire de symptômes avec un résultat de triage simulé, sans base de données."""
        requete = RequestFactory().post("/patients/medecins/m1/symptomes/", {})
        requete.user = SimpleNamespace(is_authenticated=True, patient=un_patient())
        formulaire = mock.Mock()
        formulaire.is_valid.return_value = True
        formulaire.cleaned_data = {"symptomes": [], "texte_libre": ""}
        formulaire.constantes.return_value = {}
        formulaire.auto_evaluation.return_value = {"douleur": 0, "fievre": 0, "respiration": 0, "etat_general": 0}
        resultat = SimpleNamespace(score=3, niveau=niveau, explication="e", drapeaux_rouges=[])
        cree = Triage(niveau=niveau, statut="en_attente")
        cree.pk = ObjectId()
        with mock.patch.object(vues_patients, "SymptomesForm", return_value=formulaire), \
                mock.patch.object(vues_patients, "evaluer", return_value=resultat), \
                mock.patch.object(Triage.objects, "create", return_value=cree):
            reponse = vues_patients.declarer_symptomes(requete, "m1")
        return reponse, cree

    def test_apres_les_symptomes_un_cas_non_urgent_va_au_choix_du_creneau(self):
        for niveau in (3, 4, 5):
            with self.subTest(niveau=niveau):
                reponse, cree = self.soumettre_symptomes(niveau)
                self.assertEqual(reponse.status_code, 302)
                self.assertEqual(reponse["Location"], f"/patients/triage/{cree.pk}/creneaux/")

    def test_un_cas_prioritaire_va_directement_au_resultat(self):
        for niveau in (1, 2):
            with self.subTest(niveau=niveau):
                reponse, cree = self.soumettre_symptomes(niveau)
                self.assertEqual(reponse["Location"], f"/patients/triage/{cree.pk}/")

    def test_le_tableau_de_bord_propose_le_creneau_aux_demandes_sans_rendez_vous(self):
        racine = Path(__file__).resolve().parent / "templates" / "patients"
        source = (racine / "tableau_de_bord.html").read_text(encoding="utf-8")
        self.assertIn("t.peut_reserver", source)
        self.assertIn("Choisir le jour et l'heure", source)
        self.assertIn("peut_reserver = planning.reservable", inspect_source(vues_patients.tableau_de_bord))


def inspect_source(objet):
    import inspect

    return inspect.getsource(objet)


# --- File d'attente équitable (échéances, plafond de dépassements) --------------------------------
from . import file_attente as fa  # noqa: E402
from . import suivi as suivi_mod  # noqa: E402
from .models import ReglageTriage  # noqa: E402

JOURS_OUVRES = {j: [(9, 12), (14, 17)] for j in range(5)}  # lundi à vendredi, 6 h de présence par jour
MARDI_9H = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=TUNIS)


class MinutesOuvreesTests(SimpleTestCase):
    def test_sans_horaires_temps_reel(self):
        a = LUNDI_8H
        self.assertEqual(fa.minutes_ouvrees_entre(a, a + datetime.timedelta(hours=5), {}, TUNIS), 300)
        self.assertEqual(fa.ajouter_minutes_ouvrees(a, 90, {}, TUNIS), a + datetime.timedelta(minutes=90))

    def test_seule_la_presence_du_medecin_compte(self):
        # lundi 8 h -> lundi 13 h : présence 9-12 = 180 min (la pause de 12 h à 14 h ne compte pas)
        fin = LUNDI_8H.replace(hour=13)
        self.assertEqual(fa.minutes_ouvrees_entre(LUNDI_8H, fin, JOURS_OUVRES, TUNIS), 180)

    def test_la_nuit_et_le_week_end_ne_comptent_pas(self):
        vendredi_16h = datetime.datetime(2026, 10, 23, 16, 0, tzinfo=TUNIS)
        lundi_10h = datetime.datetime(2026, 10, 26, 10, 0, tzinfo=TUNIS)
        # vendredi 16-17 (60 min) + lundi 9-10 (60 min)
        self.assertEqual(fa.minutes_ouvrees_entre(vendredi_16h, lundi_10h, JOURS_OUVRES, TUNIS), 120)

    def test_fin_avant_debut_zero(self):
        self.assertEqual(fa.minutes_ouvrees_entre(LUNDI_8H, LUNDI_8H - datetime.timedelta(hours=1), JOURS_OUVRES, TUNIS), 0)

    def test_ajouter_des_minutes_saute_les_pauses_et_les_nuits(self):
        # 30 min après lundi 11 h 45 : 15 min avant la pause, puis 15 min de l'après-midi -> 14 h 15
        debut = LUNDI_8H.replace(hour=11, minute=45)
        self.assertEqual(fa.ajouter_minutes_ouvrees(debut, 30, JOURS_OUVRES, TUNIS), LUNDI_8H.replace(hour=14, minute=15))
        # 7 h de présence depuis lundi 9 h : 6 h le lundi, puis 1 h le mardi -> mardi 10 h
        self.assertEqual(fa.ajouter_minutes_ouvrees(LUNDI_8H.replace(hour=9), 420, JOURS_OUVRES, TUNIS), MARDI_9H.replace(hour=10))

    def test_demande_hors_horaires_commence_a_l_ouverture(self):
        nuit = LUNDI_8H.replace(hour=2)
        self.assertEqual(fa.ajouter_minutes_ouvrees(nuit, 30, JOURS_OUVRES, TUNIS), LUNDI_8H.replace(hour=9, minute=30))

    def test_aller_et_retour_coherents(self):
        for minutes in (10, 95, 400, 1440):
            with self.subTest(minutes=minutes):
                fin = fa.ajouter_minutes_ouvrees(LUNDI_8H, minutes, JOURS_OUVRES, TUNIS)
                self.assertAlmostEqual(fa.minutes_ouvrees_entre(LUNDI_8H, fin, JOURS_OUVRES, TUNIS), minutes, places=3)

    def test_plage_jusqu_a_minuit(self):
        h = {0: [(20, 24)]}
        self.assertEqual(fa.minutes_ouvrees_entre(LUNDI_8H, LUNDI_8H + datetime.timedelta(days=1), h, TUNIS), 240)


class EtatDuDelaiTests(SimpleTestCase):
    def etat(self, niveau, ecoule_min, **kw):
        return fa.evaluer_delai(LUNDI_8H, niveau, LUNDI_8H + datetime.timedelta(minutes=ecoule_min), fa.DEFAUT, {}, TUNIS, **kw)

    def test_delais_par_defaut(self):
        self.assertEqual(fa.DEFAUT.delais, {2: 30, 3: 120, 4: 480, 5: 1440})
        self.assertEqual((fa.DEFAUT.plafond, fa.DEFAUT.seuil_risque, fa.DEFAUT.duree_consultation), (5, 0.75, 20))

    def test_seuils_dans_les_temps_a_risque_en_retard(self):
        for ecoule, attendu in ((0, "dans_les_temps"), (89, "dans_les_temps"), (90, "a_risque"), (119, "a_risque"),
                                (120, "en_retard"), (500, "en_retard")):
            with self.subTest(ecoule=ecoule):
                self.assertEqual(self.etat(3, ecoule).etat, attendu)

    def test_echeance_reste_et_pourcentage(self):
        d = self.etat(3, 60)
        self.assertEqual(d.echeance, LUNDI_8H + datetime.timedelta(minutes=120))
        self.assertEqual((d.cible_min, d.ecoule_min, d.reste_min, d.pourcentage), (120, 60, 60, 50))
        self.assertEqual(self.etat(3, 500).pourcentage, 100)  # la jauge ne dépasse jamais 100 %
        self.assertEqual(self.etat(3, 500).reste_min, -380)

    def test_chaque_niveau_a_son_delai(self):
        self.assertEqual([self.etat(n, 0).cible_min for n in (2, 3, 4, 5)], [30, 120, 480, 1440])

    def test_niveau_vital_et_niveau_inconnu(self):
        self.assertEqual(self.etat(1, 9999).etat, "immediat")
        self.assertEqual(self.etat(None, 0).etat, "inconnu")

    def test_un_rendez_vous_fixe_n_est_en_retard_qu_apres_son_heure(self):
        creneau = LUNDI_8H + datetime.timedelta(days=2)
        self.assertEqual(fa.delai_planifie(creneau, LUNDI_8H).etat, "planifie")
        self.assertEqual(fa.delai_planifie(creneau, creneau + datetime.timedelta(minutes=1)).etat, "en_retard")

    def test_le_retard_se_compte_en_presence_du_medecin(self):
        # niveau 4 (480 min) arrivé vendredi 16 h : lundi 9 h il n'a que 60 min de présence écoulée
        vendredi = datetime.datetime(2026, 10, 23, 16, 0, tzinfo=TUNIS)
        lundi = datetime.datetime(2026, 10, 26, 9, 0, tzinfo=TUNIS)
        d = fa.evaluer_delai(vendredi, 4, lundi, fa.DEFAUT, JOURS_OUVRES, TUNIS)
        self.assertEqual((d.etat, d.ecoule_min), ("dans_les_temps", 60))

    def test_libelles_lisibles(self):
        self.assertEqual([fa.Delai(etat=e).libelle for e in ("dans_les_temps", "a_risque", "en_retard", "planifie")],
                         ["Dans les temps", "À risque", "En retard", "Rendez-vous fixé"])

    def test_formatage_des_durees(self):
        for minutes, attendu in ((0, "0 min"), (45, "45 min"), (60, "1 h"), (130, "2 h 10"), (1440, "24 h"), (-90, "1 h 30")):
            with self.subTest(minutes=minutes):
                self.assertEqual(fa.formater_duree(minutes), attendu)


class OrdreDePassageTests(SimpleTestCase):
    """Le cas décrit : un patient peu urgent qui attend ne doit pas être dépassé indéfiniment."""

    def demande(self, niveau, arrivee, depassements=0, creneau=None):
        t = Triage(medecin_id="m1", niveau=niveau, statut="en_attente", cree_le=arrivee, nb_depassements=depassements, creneau=creneau)
        t.pk = ObjectId()
        return t

    def ordre(self, demandes, maintenant, reglage=fa.DEFAUT, horaires=None):
        return Triage.trier_file(demandes, reglage, horaires or {}, maintenant)

    def test_la_regle_actuelle_aurait_laisse_le_niveau_5_en_dernier(self):
        # contrôle de la situation de départ : tri par (niveau, arrivée) -> le niveau 5 est toujours dernier
        ancien5 = self.demande(5, LUNDI_8H)
        nouveau2 = self.demande(2, LUNDI_8H + datetime.timedelta(days=4))
        ancienne = sorted([ancien5, nouveau2], key=lambda t: (t.niveau_effectif or 5, t.cree_le))
        self.assertEqual(ancienne, [nouveau2, ancien5])

    def test_un_patient_ancien_non_protege_reste_derriere_les_urgents(self):
        # les niveaux 2 et 3 restent prioritaires : c'est la sécurité des cas urgents
        ancien5 = self.demande(5, LUNDI_8H)
        for jours in (0.5, 1.5):
            with self.subTest(jours=jours):
                arrivee = LUNDI_8H + datetime.timedelta(days=jours)
                nouveau2 = self.demande(2, arrivee)
                self.assertIs(self.ordre([nouveau2, ancien5], arrivee)[0], nouveau2)

    def test_un_patient_ancien_passe_devant_les_demandes_non_urgentes_plus_recentes(self):
        ancien5 = self.demande(5, LUNDI_8H)
        nouveau4 = self.demande(4, LUNDI_8H + datetime.timedelta(days=1.5))
        self.assertEqual(self.ordre([nouveau4, ancien5], LUNDI_8H + datetime.timedelta(days=1.5)), [ancien5, nouveau4])

    def test_garantie_apres_trois_fois_le_delai_le_patient_protege_passe_devant_les_urgents(self):
        protegee = self.demande(5, LUNDI_8H, depassements=5)  # délai cible 24 h : garantie à partir de 72 h
        for jours, premier in ((2.9, "urgent"), (3.1, "protegee")):
            with self.subTest(jours=jours):
                maintenant = LUNDI_8H + datetime.timedelta(days=jours)
                urgent = self.demande(2, maintenant)
                file = self.ordre([urgent, protegee], maintenant)
                self.assertIs(file[0], urgent if premier == "urgent" else protegee)

    def test_la_garantie_exige_d_etre_protege(self):
        # attendu 4 jours mais seulement dépassé 2 fois : pas encore protégé, donc derrière l'urgent
        pas_protegee = self.demande(5, LUNDI_8H, depassements=2)
        maintenant = LUNDI_8H + datetime.timedelta(days=4)
        urgent = self.demande(2, maintenant)
        self.assertIs(self.ordre([pas_protegee, urgent], maintenant)[0], urgent)

    def test_la_garantie_est_reglable(self):
        protegee = self.demande(5, LUNDI_8H, depassements=5)
        maintenant = LUNDI_8H + datetime.timedelta(days=1.2)  # 1,2 fois le délai
        urgent = self.demande(2, maintenant)
        souple = fa.Reglage(delais=fa.DEFAUT.delais, facteur_garantie=1.0)
        self.assertIs(self.ordre([urgent, protegee], maintenant, reglage=souple)[0], protegee)
        self.assertIs(self.ordre([urgent, protegee], maintenant)[0], urgent)  # réglage par défaut : 3 fois

    def test_groupes_de_passage_dans_l_ordre(self):
        maintenant = LUNDI_8H + datetime.timedelta(days=5)
        vital = self.demande(1, maintenant)
        garantie = self.demande(5, LUNDI_8H, depassements=9)            # protégée, 5 jours = 5 fois son délai
        urgent2 = self.demande(2, maintenant - datetime.timedelta(minutes=5))
        urgent3 = self.demande(3, maintenant - datetime.timedelta(minutes=50))
        protegee4 = self.demande(4, LUNDI_8H + datetime.timedelta(days=4.5), depassements=5)  # protégée, 1,5 fois son délai
        autre5 = self.demande(5, LUNDI_8H + datetime.timedelta(days=4.5, hours=1))
        melange = [autre5, urgent3, protegee4, garantie, urgent2, vital]
        self.assertEqual(self.ordre(melange, maintenant), [vital, garantie, urgent2, urgent3, protegee4, autre5])

    def test_cas_urgent_passe_devant_tant_que_l_ancien_n_est_pas_en_retard(self):
        ancien5 = self.demande(5, LUNDI_8H)
        nouveau3 = self.demande(3, LUNDI_8H + datetime.timedelta(hours=2))
        self.assertEqual(self.ordre([ancien5, nouveau3], LUNDI_8H + datetime.timedelta(hours=2)), [nouveau3, ancien5])

    def test_a_niveau_egal_premier_arrive_premier_servi(self):
        a, b = self.demande(4, LUNDI_8H), self.demande(4, LUNDI_8H + datetime.timedelta(minutes=5))
        self.assertEqual(self.ordre([b, a], LUNDI_8H + datetime.timedelta(hours=1)), [a, b])

    def test_le_cas_vital_est_toujours_premier(self):
        vital = self.demande(1, LUNDI_8H + datetime.timedelta(days=3))
        tres_ancien = self.demande(5, LUNDI_8H, depassements=99)
        self.assertEqual(self.ordre([tres_ancien, vital], LUNDI_8H + datetime.timedelta(days=9))[0], vital)

    def test_une_demande_protegee_passe_devant_les_demandes_non_urgentes(self):
        protegee = self.demande(5, LUNDI_8H, depassements=5)
        standard = self.demande(4, LUNDI_8H + datetime.timedelta(minutes=10))  # échéance bien plus proche, mais non protégée
        urgent = self.demande(2, LUNDI_8H + datetime.timedelta(minutes=10))
        self.assertEqual(self.ordre([standard, protegee, urgent], LUNDI_8H + datetime.timedelta(minutes=10)), [urgent, protegee, standard])

    def test_avant_le_plafond_la_demande_n_est_pas_protegee(self):
        t = self.demande(5, LUNDI_8H, depassements=4)
        self.assertFalse(t.est_protegee())
        self.assertTrue(self.demande(5, LUNDI_8H, depassements=5).est_protegee())

    def test_le_plafond_est_reglable(self):
        souple = fa.Reglage(delais=fa.DEFAUT.delais, plafond=2)
        self.assertTrue(self.demande(5, LUNDI_8H, depassements=2).est_protegee(souple))

    def test_les_rendez_vous_fixes_ne_sont_pas_dans_la_file(self):
        libre = self.demande(4, LUNDI_8H)
        fixe = self.demande(4, LUNDI_8H, creneau=LUNDI_8H + datetime.timedelta(days=1))
        self.assertEqual(self.ordre([libre, fixe], LUNDI_8H), [libre])
        self.assertIsNone(fixe.place_dans_la_file(file=[libre]))
        self.assertEqual(libre.place_dans_la_file(file=[libre]), (1, 1))

    def test_demande_sans_niveau_traitee_comme_non_urgente(self):
        sans = self.demande(None, LUNDI_8H)
        urgent = self.demande(3, LUNDI_8H + datetime.timedelta(minutes=1))
        self.assertEqual(self.ordre([sans, urgent], LUNDI_8H + datetime.timedelta(minutes=1)), [urgent, sans])

    def test_le_niveau_requalifie_par_le_medecin_change_l_echeance(self):
        t = self.demande(5, LUNDI_8H)
        t.niveau_medecin = 2  # le médecin juge la demande très urgente : l'attente déjà subie compte
        d = t.delai_calcule(fa.DEFAUT, {}, LUNDI_8H + datetime.timedelta(hours=1))
        self.assertEqual(d.etat, "en_retard")

    def test_nb_depassements_absent_en_base_vaut_zero(self):
        t = self.demande(5, LUNDI_8H, depassements=None)
        self.assertFalse(t.est_protegee())
        self.assertEqual(self.ordre([t], LUNDI_8H), [t])

    def test_depassements_comptes_pour_les_plus_anciennes_seulement(self):
        ancienne = (1, LUNDI_8H, None)
        recente = (2, LUNDI_8H + datetime.timedelta(hours=3), None)
        fixe = (3, LUNDI_8H, LUNDI_8H + datetime.timedelta(days=1))
        prise = (LUNDI_8H + datetime.timedelta(hours=1), None)
        self.assertEqual(fa.depassees_par(prise, [ancienne, recente, fixe]), [1])  # ni la plus récente, ni le rendez-vous fixé
        self.assertEqual(fa.depassees_par((LUNDI_8H, None), [ancienne, recente]), [])  # la plus ancienne ne double personne
        self.assertEqual(fa.depassees_par((LUNDI_8H + datetime.timedelta(hours=1), LUNDI_8H), [ancienne]), [])  # un rendez-vous ne double personne

    def test_enregistrer_depassements_incremente_les_demandes_plus_anciennes(self):
        ancienne = self.demande(5, LUNDI_8H, depassements=1)
        recente = self.demande(2, LUNDI_8H + datetime.timedelta(hours=5))
        prise = self.demande(3, LUNDI_8H + datetime.timedelta(hours=1))
        with mock.patch.object(Triage.objects, "filter", return_value=[ancienne, recente, prise]), \
                mock.patch.object(Triage, "save") as sauvegarde:
            nombre = prise.enregistrer_depassements()
        self.assertEqual((nombre, ancienne.nb_depassements, recente.nb_depassements), (1, 2, 0))
        sauvegarde.assert_called_once_with(update_fields=["nb_depassements"])

    def flux_continu_de_cas_urgents(self, reglage, etapes=1700):
        """Le cas décrit : un patient de niveau 5 arrive, puis un nouveau cas de niveau 2 toutes les 10 minutes,
        autant que le médecin peut en voir. Renvoie l'instant où le patient de niveau 5 est vu, ou None."""
        horaires = {j: [(8, 20)] for j in range(7)}
        ancien5 = self.demande(5, LUNDI_8H)
        file = [ancien5]
        for etape in range(1, etapes):
            maintenant = LUNDI_8H + datetime.timedelta(minutes=10 * etape)
            file.append(self.demande(2, maintenant))
            file = Triage.trier_file(file, reglage, horaires, maintenant)
            vu = file.pop(0)
            for i in fa.depassees_par((vu.cree_le, vu.creneau), [(t.pk, t.cree_le, t.creneau) for t in file]):
                for t in file:
                    if t.pk == i:
                        t.nb_depassements += 1  # comme le back-office quand le médecin prend la demande
            if vu is ancien5:
                return maintenant
        return None

    def test_simulation_un_flux_continu_de_cas_urgents_ne_bloque_pas_un_patient_pour_toujours(self):
        horaires = {j: [(8, 20)] for j in range(7)}
        vu_a = self.flux_continu_de_cas_urgents(fa.DEFAUT)
        self.assertIsNotNone(vu_a, "le patient de niveau 5 n'a jamais été vu")
        garantie = fa.ajouter_minutes_ouvrees(LUNDI_8H, fa.DEFAUT.facteur_garantie * fa.DEFAUT.delais[5], horaires, TUNIS)
        self.assertLessEqual(vu_a, garantie + datetime.timedelta(minutes=30))  # au plus tard à 3 fois son délai cible
        self.assertGreater(vu_a, LUNDI_8H + datetime.timedelta(hours=48))  # les urgents ont bien été servis avant lui

    def test_simulation_sans_la_garantie_le_patient_serait_oublie(self):
        # contrôle négatif : sans filet de sécurité, le flux urgent saturé bloque indéfiniment le niveau 5
        sans_garantie = fa.Reglage(delais=fa.DEFAUT.delais, facteur_garantie=1e9)
        self.assertIsNone(self.flux_continu_de_cas_urgents(sans_garantie))


class ReglageTriageTests(SimpleTestCase):
    def test_valeurs_par_defaut_identiques_au_module(self):
        r = ReglageTriage().vers_reglage()
        self.assertEqual(r, fa.DEFAUT)

    def test_conversion(self):
        r = ReglageTriage(delai_niveau_2=10, delai_niveau_3=60, delai_niveau_4=300, delai_niveau_5=900,
                          plafond_depassements=3, seuil_risque=60, duree_consultation=15, facteur_garantie=4).vers_reglage()
        self.assertEqual(r.delais, {2: 10, 3: 60, 4: 300, 5: 900})
        self.assertEqual((r.plafond, r.seuil_risque, r.duree_consultation, r.facteur_garantie), (3, 0.6, 15, 4.0))

    def test_les_delais_doivent_augmenter_avec_le_niveau(self):
        with self.assertRaises(ValidationError):
            ReglageTriage(delai_niveau_3=20).clean()  # 20 < 30 (niveau 2)
        with self.assertRaises(ValidationError):
            ReglageTriage(delai_niveau_4=120).clean()  # égal au niveau 3
        ReglageTriage().clean()

    def test_bornes_des_champs(self):
        for champ, valeur in (("delai_niveau_2", 1), ("plafond_depassements", 0), ("plafond_depassements", 21),
                              ("seuil_risque", 49), ("seuil_risque", 96), ("duree_consultation", 4), ("duree_consultation", 121),
                              ("facteur_garantie", 1), ("facteur_garantie", 11)):
            with self.subTest(champ=champ, valeur=valeur):
                with self.assertRaises(ValidationError) as ctx:
                    ReglageTriage(**{champ: valeur}).clean_fields(exclude=["modifie_le"])
                self.assertIn(champ, ctx.exception.message_dict)

    def test_actuel_sans_ligne_en_base_donne_les_valeurs_par_defaut(self):
        with mock.patch.object(ReglageTriage.objects, "first", return_value=None):
            self.assertEqual(ReglageTriage.actuel().vers_reglage(), fa.DEFAUT)


class SuiviTests(SimpleTestCase):
    def demande(self, niveau, arrivee, medecin="m1", creneau=None):
        t = Triage(medecin_id=medecin, niveau=niveau, statut="en_attente", cree_le=arrivee, creneau=creneau, nb_depassements=0)
        t.pk = ObjectId()
        return t

    def test_annotation_de_la_file_et_du_planning(self):
        maintenant = datetime.datetime(2026, 10, 21, 10, 0, tzinfo=TUNIS)  # un mercredi, 10 h
        a = self.demande(4, maintenant - datetime.timedelta(hours=2))
        b = self.demande(2, maintenant - datetime.timedelta(minutes=5))
        c = self.demande(3, maintenant - datetime.timedelta(hours=1), creneau=maintenant + datetime.timedelta(days=1))
        autre = self.demande(5, maintenant, medecin="m2")
        groupes = suivi_mod.annoter([a, b, c, autre], fa.DEFAUT, maintenant)
        self.assertEqual(set(groupes), {"m1", "m2"})
        self.assertEqual(groupes["m1"]["file"], [b, a])  # le très urgent d'abord
        self.assertEqual(groupes["m1"]["planning"], [c])
        self.assertEqual((b.place, a.place, c.place), ((1, 2), (2, 2), None))
        self.assertEqual(c.delai.etat, "planifie")
        self.assertEqual(c.prise_en_charge_estimee, c.creneau)
        self.assertEqual((autre.place, autre.protegee), ((1, 1), False))

    def test_prise_en_charge_estimee_selon_la_position(self):
        maintenant = datetime.datetime(2026, 10, 21, 10, 0, tzinfo=TUNIS)
        demandes = [self.demande(4, maintenant - datetime.timedelta(minutes=10 - i)) for i in range(3)]
        suivi_mod.annoter(demandes, fa.DEFAUT, maintenant)
        premiere, deuxieme, troisieme = demandes
        self.assertEqual(premiere.prise_en_charge_estimee, maintenant)  # elle est la prochaine
        self.assertEqual(deuxieme.prise_en_charge_estimee, maintenant + datetime.timedelta(minutes=20))
        self.assertEqual(troisieme.prise_en_charge_estimee, maintenant + datetime.timedelta(minutes=40))

    def test_file_vide(self):
        self.assertEqual(suivi_mod.annoter([], fa.DEFAUT), {})

    def test_horaires_des_medecins(self):
        self.assertTrue(suivi_mod.horaires_du_medecin("m1"))
        self.assertEqual(suivi_mod.horaires_du_medecin("zzz"), {})
        self.assertEqual(suivi_mod.horaires_du_medecin("m3"), {})  # médecin indisponible


# --- Pages : suivi de la file, liste des médecins, grille des créneaux ------------------------------
def FauxPatient(nom="Amel Trabelsi"):
    """Patient de test (non enregistré) dont on peut afficher le nom."""
    prenom, _, famille = nom.partition(" ")
    patient = Patient(user=get_user_model()(username="x", first_name=prenom, last_name=famille), date_naissance=datetime.date(1990, 5, 4))
    patient.pk = ObjectId()
    return patient


class SuiviPagesTests(SimpleTestCase):
    def requete(self, nom="tableau_de_bord"):
        requete = RequestFactory().get("/x/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="A", username="a",
                                       get_full_name=lambda: "A")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def suivi(self, etat="dans_les_temps", ratio=0.3, place=(2, 5), depassements=0, protegee=False, creneau=None, reste=84):
        delai = fa.Delai(etat=etat, echeance=LUNDI_8H + datetime.timedelta(hours=3), cible_min=120, ecoule_min=36, reste_min=reste, ratio=ratio)
        if creneau:
            delai = fa.Delai(etat=etat, echeance=creneau)
        return SimpleNamespace(creneau=creneau, place=None if creneau else place, delai=delai, protegee=protegee,
                               nb_depassements=depassements, prise_en_charge_estimee=LUNDI_8H + datetime.timedelta(hours=1), pk="x")

    def rendre(self, **kw):
        return render_to_string("patients/_suivi_attente.html", {"t": self.suivi(**kw)}, self.requete())

    def test_dans_les_temps(self):
        html = self.rendre()
        self.assertIn("sev sev-legere", html)
        self.assertIn(">Dans les temps<", html)
        self.assertIn("2e sur 5", html)
        self.assertIn("Prise en charge visée avant", html)
        self.assertIn("il reste 1 h 24 de présence du médecin", html)
        self.assertIn("Prise en charge estimée", html)
        self.assertRegex(html, r"lundi 19 octobre, vers 09:00")  # « vers » n'est pas lu comme des codes de format de date
        self.assertNotIn("CET", html)
        self.assertNotIn("alert", html)

    def test_jauge_accessible(self):
        html = self.rendre(ratio=0.3)
        self.assertIn('role="progressbar"', html)
        self.assertIn('aria-valuenow="30"', html)
        self.assertIn('aria-label="Part du délai cible écoulée"', html)
        self.assertIn('style="width: 30%"', html)
        self.assertIn("meter-dans_les_temps", html)

    def test_premiere_place(self):
        self.assertIn("1re sur 3", self.rendre(place=(1, 3)))

    def test_a_risque_avertit_sans_alarmer(self):
        html = self.rendre(etat="a_risque", ratio=0.8)
        self.assertIn("sev-moderee", html)
        self.assertIn("alert-warn", html)
        self.assertIn("approche du délai visé", html)
        self.assertNotIn("alert-danger", html)
        self.assertIn("meter-a_risque", html)

    def test_en_retard_informe_et_propose_une_issue(self):
        html = self.rendre(etat="en_retard", ratio=1.4, reste=-48)
        self.assertIn("sev-severe", html)
        self.assertIn('role="alert"', html)
        self.assertIn("délai dépassé de 48 min", html)
        self.assertIn("voir d'autres médecins", html)
        self.assertIn('style="width: 100%"', html)  # la jauge reste à 100 %

    def test_l_etat_n_est_pas_indique_par_la_couleur_seule(self):
        for etat, texte in (("dans_les_temps", "Dans les temps"), ("a_risque", "À risque"), ("en_retard", "En retard")):
            with self.subTest(etat=etat):
                self.assertIn(f">{texte}<", self.rendre(etat=etat))

    def test_depassements_expliques_avec_accord_grammatical(self):
        self.assertIn("1 personne plus urgente est passée devant vous", self.rendre(depassements=1))
        self.assertIn("3 personnes plus urgentes sont passées devant vous", self.rendre(depassements=3))
        self.assertNotIn("passée", self.rendre(depassements=0))

    def test_cas_vital_affiche_l_heure_estimee_et_explique_l_absence_de_rendez_vous(self):
        t = self.suivi(etat="immediat", place=(1, 5))
        t.delai = fa.Delai(etat="immediat")  # un cas vital n'a ni échéance ni créneau
        html = render_to_string("patients/_suivi_attente.html", {"t": t}, self.requete())
        self.assertIn(">Immédiat<", html)
        self.assertIn("1re sur 5", html)
        self.assertIn("Pas de rendez-vous à fixer", html)
        self.assertRegex(html, r"Prise en charge estimée : <strong[^>]*>lundi 19 octobre, vers 09:00</strong>")
        self.assertNotIn("progressbar", html)  # pas de jauge : il n'y a pas de délai à respecter

    def test_cas_vital_sans_estimation_n_affiche_que_l_explication(self):
        t = self.suivi(etat="immediat", place=(1, 1))
        t.delai, t.prise_en_charge_estimee = fa.Delai(etat="immediat"), None
        html = render_to_string("patients/_suivi_attente.html", {"t": t}, self.requete())
        self.assertIn("Pas de rendez-vous à fixer", html)
        self.assertNotIn("Prise en charge estimée", html)

    def test_cas_prioritaire_sur_le_resultat_renvoie_au_suivi(self):
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr X", niveau=1, statut="en_attente", explication="e")
        t.pk = ObjectId()
        t.__dict__.update(self.suivi(etat="immediat", place=(1, 2)).__dict__ | {"creneau": None})
        t.delai = fa.Delai(etat="immediat")
        html = render_to_string("patients/resultat.html", {"triage": t, "message": "m", "propositions": [], "can_book": False}, self.requete("resultat"))
        self.assertIn("il n'y a pas de créneau à choisir", html)
        self.assertIn("indiquée dans le suivi ci-dessus", html)
        self.assertIn("Prise en charge estimée", html)  # l'heure est bien affichée dans le bloc de suivi
        self.assertNotIn("Choisir un créneau", html)

    def test_demande_protegee(self):
        html = self.rendre(protegee=True, depassements=5)
        self.assertIn("Votre demande est protégée", html)
        self.assertIn("seuls les cas urgents peuvent encore passer devant vous", html)
        self.assertNotIn("sont passées devant vous", html)

    def test_rendez_vous_fixe(self):
        html = self.rendre(etat="planifie", creneau=LUNDI_8H + datetime.timedelta(days=1, hours=2))
        self.assertIn("sev-info", html)
        self.assertIn(">Rendez-vous fixé<", html)
        self.assertIn("à 10:00", html)
        self.assertNotIn("progressbar", html)
        self.assertNotIn("Votre place", html)

    def test_rendez_vous_manque(self):
        html = self.rendre(etat="en_retard", creneau=LUNDI_8H)
        self.assertIn("L'heure de votre rendez-vous est passée", html)

    def test_sans_delai_rien_n_est_affiche(self):
        html = render_to_string("patients/_suivi_attente.html", {"t": SimpleNamespace(delai=None)}, self.requete())
        self.assertNotIn("suivi", html)

    def test_le_tableau_de_bord_inclut_le_suivi_et_le_bouton(self):
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr Sara Benali", medecin_specialite="MG", niveau=4,
                   statut="en_attente", cree_le=LUNDI_8H)
        t.pk = ObjectId()
        t.__dict__.update(self.suivi().__dict__ | {"creneau": None})
        t.peut_reserver, t.propositions = True, []
        html = render_to_string("patients/tableau_de_bord.html", {"en_cours": [t], "historique": []}, self.requete())
        self.assertIn("Suivi de la demande", html)
        self.assertIn("2e sur 5", html)
        self.assertIn("Choisir le jour et l'heure", html)
        self.assertEqual(html.count("2e sur 5"), 1)  # une seule fois : l'ancienne ligne a disparu

    def test_le_resultat_affiche_le_suivi_des_demandes_en_attente(self):
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr X", niveau=4, statut="en_attente", explication="e")
        t.pk = ObjectId()
        t.__dict__.update(self.suivi().__dict__ | {"creneau": None})
        html = render_to_string("patients/resultat.html", {"triage": t, "message": "m", "propositions": [], "can_book": True}, self.requete("resultat"))
        self.assertIn("Suivi de votre demande", html)
        t.statut = "termine"
        self.assertNotIn("Suivi de votre demande", render_to_string("patients/resultat.html", {"triage": t, "message": "m", "propositions": [], "can_book": False}, self.requete("resultat")))

    def test_liste_des_medecins_avec_prochain_creneau_et_attente(self):
        medecins = [
            dict(medecins_test.trouver("m1"), prochain_creneau=LUNDI_8H.replace(hour=10), en_attente=3),
            dict(medecins_test.trouver("m2"), prochain_creneau=None, en_attente=1),
            dict(medecins_test.trouver("m3"), prochain_creneau=None, en_attente=0),
        ]
        html = render_to_string("patients/medecins.html", {"medecins": medecins, "specialites": [], "villes": [], "specialite": "", "ville": ""}, self.requete("medecins"))
        self.assertIn("Prochain créneau", html)
        self.assertRegex(html, r"(?i)19 oct[^<]*10:00")
        self.assertIn("3 patients", html)
        self.assertIn("1 patient<", html.replace("patient\n", "patient<"))
        self.assertIn("aucun pour le moment", html)
        self.assertEqual(html.count("Prochain créneau"), 2)  # le médecin indisponible n'affiche pas ces lignes

    def test_grille_les_creneaux_pris_sont_visibles_mais_non_selectionnables(self):
        grille = planning.grille({0: [(9, 11)]}, LUNDI_8H - datetime.timedelta(days=1), pris=[LUNDI_8H.replace(hour=10)])
        jours = planning.grouper_grille(grille)[:1]
        self.assertEqual(jours[0]["total"], 3)  # 4 créneaux, 1 pris
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr X", niveau=4, statut="en_attente")
        t.pk = ObjectId()
        html = render_to_string("patients/creneaux.html", {"triage": t, "medecin": {}, "jours": jours, "total": 3, "duree": 30}, self.requete("creneaux"))
        self.assertEqual(html.count('type="radio" name="debut"'), 3)
        self.assertEqual(html.count("slot-pris"), 1)
        self.assertIn("<s>10:00</s>", html)
        self.assertIn("déjà pris", html)
        self.assertIn("3 créneaux libres", html)
        self.assertIn("Les créneaux barrés sont déjà réservés", html)

    def test_un_jour_complet_est_indique(self):
        grille = planning.grille({0: [(9, 10)]}, LUNDI_8H - datetime.timedelta(days=1), pris=[LUNDI_8H.replace(hour=9), LUNDI_8H.replace(hour=9, minute=30)])
        jours = planning.grouper_grille(grille)[:1]
        self.assertEqual(jours[0]["total"], 0)
        t = Triage(patient=un_patient(), medecin_id="m1", medecin_nom="Dr X", niveau=4, statut="en_attente")
        t.pk = ObjectId()
        html = render_to_string("patients/creneaux.html", {"triage": t, "medecin": {}, "jours": jours, "total": 1, "duree": 30}, self.requete("creneaux"))
        self.assertIn("complet", html)

    def test_grille_contient_tous_les_creneaux_libres_ou_non(self):
        pris = [LUNDI_8H.replace(hour=10)]
        grille = planning.grille({0: [(9, 12)]}, LUNDI_8H - datetime.timedelta(days=1), pris)
        premier_jour = [(c, libre) for c, libre in grille if c.date() == LUNDI_8H.date()]
        self.assertEqual(len(premier_jour), 6)
        self.assertEqual([libre for _, libre in premier_jour], [True, True, False, True, True, True])
        self.assertEqual(sum(1 for _, libre in grille if libre), len(planning.generer({0: [(9, 12)]}, LUNDI_8H - datetime.timedelta(days=1), pris)))

    def test_la_page_de_la_file_du_medecin_montre_etat_et_planning(self):
        d = Triage(patient=FauxPatient(), medecin_id="m1", niveau=4, statut="en_attente", explication="x", cree_le=LUNDI_8H)
        d.pk = ObjectId()
        d.__dict__.update(self.suivi(depassements=2).__dict__ | {"creneau": None})
        p = Triage(patient=FauxPatient("Sonia Mejri"), medecin_id="m1", niveau=3, statut="en_attente", explication="x", cree_le=LUNDI_8H)
        p.pk = ObjectId()
        p.__dict__.update(self.suivi(etat="planifie", creneau=LUNDI_8H + datetime.timedelta(days=1)).__dict__)
        html = render_to_string("patients/file_medecin.html", {"medecin": medecins_test.trouver("m1"), "demandes": [d], "planning": [p], "medecins": medecins_test.tous()}, self.requete("file_medecin_test"))
        self.assertIn("Rendez-vous fixés", html)
        self.assertIn("File d&#x27;attente", html.replace("File d'attente", "File d&#x27;attente"))
        self.assertIn("Sonia Mejri", html)
        self.assertIn("Amel Trabelsi", html)
        self.assertIn("dépassée 2 fois", html)
        self.assertIn("Dans les temps", html)

    def test_les_styles_du_suivi_sont_presents(self):
        css = (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")
        for classe in (".meter-a_risque", ".meter-en_retard", ".sev-info", ".alert-warn", ".slot-pris", ".doctor-info", ".kpi-warn"):
            self.assertIn(classe, css)

    def test_filtres_de_gabarit(self):
        from .templatetags import suivi_filtres as f

        self.assertEqual(f.duree(90), "1 h 30")
        self.assertEqual(f.duree(None), "")
        self.assertEqual(f.duree("abc"), "")
        self.assertEqual(f.classe_etat("a_risque"), "sev-moderee")
        self.assertEqual(f.classe_etat("en_retard"), "sev-severe")
        self.assertEqual(f.classe_etat("dans_les_temps"), "sev-legere")
        self.assertEqual(f.classe_etat("planifie"), "sev-info")
        self.assertEqual(f.classe_etat("inconnu"), "")

    def test_le_parcours_de_creation_applique_le_double_verrou(self):
        import inspect

        source = inspect.getsource(vues_patients.creneaux)
        self.assertIn("planning.grille(horaires, maintenant, pris)", source)  # les créneaux pris restent visibles, grisés
        self.assertLess(source.index("choix not in disponibles"), source.index("triage.save"))  # vérifié AVANT l'enregistrement
        self.assertIn("Triage.creneaux_pris(triage.medecin_id, exclure_pk=triage.pk)", source.split("Second verrou")[1])  # et APRÈS
        self.assertIn("triage.creneau = ancien", source)  # annulation en cas de conflit simultané


# --- Analyse automatique du dossier (assistant à règles) ----------------------------------------------
from . import analyse_dossier as ad  # noqa: E402
from . import analyse_service  # noqa: E402

MAINTENANT = datetime.datetime(2026, 10, 22, 10, 0, tzinfo=TUNIS)


def mesure_ad(type_, valeur, jours=1, valeur2=None):
    return {"type": type_, "valeur": valeur, "valeur2": valeur2, "mesure_le": MAINTENANT - datetime.timedelta(days=jours)}


def allergie_ad(substance="Pénicilline", gravite="severe", active=True):
    return {"substance": substance, "gravite": gravite, "active": active}


def analyser_cas(**kw):
    """Analyse d'un patient type : tout est renseigné et il a une allergie (donc dossier « calme » par défaut)."""
    valeurs = dict(age=35, sexe="F", groupe_sanguin="O+", antecedents="", traitements="", allergies=[allergie_ad("Arachide", "legere")],
                   mesures=[], manquants=[], total_controles=4, maintenant=MAINTENANT)
    valeurs.update(kw)
    return ad.analyser(**valeurs)


def titres(analyse, gravite=None):
    return [p.titre for p in analyse.points if gravite is None or p.gravite == gravite]


class AnalyseTexteTests(SimpleTestCase):
    def test_normalisation(self):
        self.assertEqual(ad.normaliser("Pénicilline, 2x/jour !"), "penicilline 2x jour")
        self.assertEqual(ad.normaliser(None), "")
        self.assertEqual(ad.normaliser("ÉPILEPSIE"), "epilepsie")

    def test_antecedents_reperes_malgre_accents_et_majuscules(self):
        self.assertEqual(ad.conditions_reperees("Asthme depuis l'enfance, Hypertension artérielle (HTA)"), ["asthme", "hypertension"])
        self.assertEqual(ad.conditions_reperees("DIABÈTE de type 2"), ["diabète"])

    def test_negation_ignoree(self):
        for texte in ("pas de diabète", "Sans asthme", "non diabétique", "aucun problème cardiaque, jamais d'asthme", "ni diabète ni asthme"):
            with self.subTest(texte=texte):
                self.assertEqual(ad.conditions_reperees(texte), [])

    def test_la_negation_ne_deborde_pas_sur_la_proposition_suivante(self):
        self.assertEqual(ad.conditions_reperees("pas de diabète, asthme"), ["asthme"])
        self.assertEqual(ad.conditions_reperees("pas de diabète. Hypertension"), ["hypertension"])

    def test_antecedent_familial_n_est_pas_celui_du_patient(self):
        self.assertEqual(ad.conditions_reperees("mon père est diabétique"), [])
        self.assertEqual(ad.conditions_reperees("ma mère a un cancer, moi asthme"), ["asthme"])
        self.assertEqual(ad.conditions_reperees("grand-père hypertendu"), [])

    def test_mot_entier_seulement(self):
        self.assertEqual(ad.conditions_reperees("thyroidectomie"), [])
        self.assertEqual(ad.conditions_reperees("thyroïde"), ["problème de thyroïde"])

    def test_texte_vide(self):
        self.assertEqual(ad.conditions_reperees(""), [])
        self.assertEqual(ad.conditions_reperees(None), [])
        self.assertEqual(ad.medicaments_reperes(None), [])

    def test_medicaments_reconnus_par_nom_ou_marque(self):
        self.assertEqual(ad.medicaments_reperes("Ventoline 2 bouffées si besoin, Doliprane, metformine 850 mg"), ["salbutamol", "metformine"])
        self.assertEqual(ad.medicaments_reperes("Glucophage, Lantus"), ["metformine", "insuline"])
        self.assertEqual(ad.medicaments_reperes("des vitamines"), [])

    def test_familles_de_medicaments(self):
        self.assertEqual(ad.familles_de("Pénicilline"), ["penicillines"])
        self.assertEqual(ad.familles_de("Amoxicilline 1 g"), ["penicillines"])
        self.assertEqual(ad.familles_de("aspirine"), ["ains"])
        self.assertEqual(ad.familles_de("Arachide"), [])


class AnalyseRegleTraitementsTests(SimpleTestCase):
    def test_traitement_de_la_meme_famille_que_l_allergie(self):
        a = analyser_cas(allergies=[allergie_ad("Pénicilline")], traitements="Amoxicilline 1g matin et soir")
        self.assertIn("Traitement et allergie de la même famille", titres(a, "important"))
        p = next(p for p in a.points if p.titre.startswith("Traitement et allergie"))
        self.assertIn("amoxicilline", p.detail)
        self.assertIn("Pénicilline", p.detail)
        self.assertEqual(p.action, "rdv")
        self.assertEqual(a.vigilance, "important")

    def test_allergie_disparue_ne_declenche_rien(self):
        a = analyser_cas(allergies=[allergie_ad("Pénicilline", active=False)], traitements="Amoxicilline")
        self.assertNotIn("Traitement et allergie de la même famille", titres(a))

    def test_autre_famille_aucune_alerte(self):
        a = analyser_cas(allergies=[allergie_ad("Pénicilline")], traitements="Doliprane")
        self.assertEqual(titres(a, "important"), [])

    def test_aspirine_et_allergie_aux_anti_inflammatoires(self):
        a = analyser_cas(allergies=[allergie_ad("Ibuprofène", "moderee")], traitements="Kardegic 75")
        self.assertIn("Traitement et allergie de la même famille", titres(a))

    def test_reaction_croisee_penicilline_cephalosporine(self):
        a = analyser_cas(allergies=[allergie_ad("Pénicilline")], traitements="Céfixime")
        self.assertIn("Réaction croisée possible", titres(a, "attention"))
        self.assertEqual(titres(a, "important"), [])

    def test_anticoagulant_et_anti_inflammatoire(self):
        a = analyser_cas(traitements="Previscan, ibuprofène si douleur")
        self.assertIn("Anticoagulant et anti-inflammatoire", titres(a, "important"))
        self.assertEqual(titres(analyser_cas(traitements="Previscan"), "important"), [])
        self.assertEqual(titres(analyser_cas(traitements="ibuprofène"), "important"), [])

    def test_traitement_sans_antecedent_correspondant(self):
        a = analyser_cas(traitements="Ventoline")
        self.assertIn("Un antécédent semble manquer (asthme)", titres(a, "info"))
        self.assertEqual(next(p for p in a.points if "antécédent semble" in p.titre).action, "completer")

    def test_pas_de_remarque_si_l_antecedent_est_indique(self):
        for traitements, antecedents in (("Ventoline", "Asthme"), ("Ventoline", "BPCO"), ("Metformine", "Diabète de type 2"), ("Bisoprolol", "infarctus en 2019"), ("Amlodipine", "HTA")):
            with self.subTest(traitements=traitements):
                self.assertFalse([t for t in titres(analyser_cas(traitements=traitements, antecedents=antecedents)) if "antécédent semble" in t])

    def test_un_antecedent_nie_ne_compte_pas(self):
        a = analyser_cas(traitements="Metformine", antecedents="pas de diabète")
        self.assertIn("Un antécédent semble manquer (diabète)", titres(a))

    def test_anticoagulant_seul_ne_demande_pas_d_antecedent(self):
        self.assertFalse([t for t in titres(analyser_cas(traitements="Eliquis")) if "antécédent semble" in t])


class AnalyseRegleMesuresTests(SimpleTestCase):
    def points(self, mesures, **kw):
        return analyser_cas(mesures=mesures, **kw)

    def test_tension_normale_rien(self):
        self.assertEqual(titres(self.points([mesure_ad("tension", 120, valeur2=80)])), [])

    def test_une_tension_elevee_invite_a_refaire_la_mesure(self):
        a = self.points([mesure_ad("tension", 150, valeur2=95)])
        self.assertEqual(titres(a, "attention"), ["Tension élevée"])
        self.assertEqual(a.points[0].action, "mesure_nouvelle")
        self.assertEqual(a.vigilance, "a_surveiller")

    def test_tension_elevee_a_plusieurs_reprises(self):
        a = self.points([mesure_ad("tension", 150, 5, 95), mesure_ad("tension", 145, 1, 92)])
        self.assertEqual(titres(a, "attention"), ["Tension anormale à plusieurs reprises"])
        self.assertEqual(a.points[0].action, "rdv")

    def test_tension_tres_elevee_ou_tres_basse_importante(self):
        self.assertEqual(titres(self.points([mesure_ad("tension", 190, valeur2=100)]), "important"), ["Tension très élevée"])
        self.assertEqual(titres(self.points([mesure_ad("tension", 150, valeur2=115)]), "important"), ["Tension très élevée"])
        self.assertEqual(titres(self.points([mesure_ad("tension", 75, valeur2=50)]), "important"), ["Tension très basse"])

    def test_tension_basse(self):
        self.assertEqual(titres(self.points([mesure_ad("tension", 85, valeur2=55)]), "attention"), ["Tension basse"])

    def test_les_mesures_de_plus_d_un_mois_sont_ignorees(self):
        self.assertEqual(titres(self.points([mesure_ad("tension", 190, 31, 110)])), [])

    def test_glycemie(self):
        cas = ((2.1, "important", "Glycémie très élevée"), (1.3, "attention", "Glycémie élevée"), (0.6, "attention", "Glycémie basse"),
               (0.5, "important", "Glycémie très basse"), (0.9, None, None))
        for valeur, gravite, titre in cas:
            with self.subTest(valeur=valeur):
                a = self.points([mesure_ad("glycemie", valeur)])
                self.assertEqual(titres(a, gravite) if gravite else titres(a), [titre] if titre else [])

    def test_saturation(self):
        self.assertEqual(titres(self.points([mesure_ad("saturation", 88)]), "important"), ["Saturation en oxygène très basse"])
        self.assertEqual(titres(self.points([mesure_ad("saturation", 92)]), "attention"), ["Saturation en oxygène basse"])
        self.assertEqual(titres(self.points([mesure_ad("saturation", 97)])), [])

    def test_temperature_ne_compte_que_quelques_jours(self):
        self.assertEqual(titres(self.points([mesure_ad("temperature", 38.5, 2)]), "attention"), ["Fièvre"])
        self.assertEqual(titres(self.points([mesure_ad("temperature", 40.2, 1)]), "important"), ["Fièvre très élevée"])
        self.assertEqual(titres(self.points([mesure_ad("temperature", 38.5, 10)])), [])  # une fièvre d'il y a 10 jours est passée
        self.assertEqual(titres(self.points([mesure_ad("temperature", 35.0, 1)]), "attention"), ["Température basse"])

    def test_pouls(self):
        self.assertEqual(titres(self.points([mesure_ad("frequence", 140)]), "important"), ["Pouls très anormal"])
        self.assertEqual(titres(self.points([mesure_ad("frequence", 105)]), "attention"), ["Pouls inhabituel"])
        self.assertEqual(titres(self.points([mesure_ad("frequence", 45)]), "attention"), ["Pouls inhabituel"])
        self.assertEqual(titres(self.points([mesure_ad("frequence", 72)])), [])

    def test_variation_de_poids(self):
        a = self.points([mesure_ad("poids", 70, 20), mesure_ad("poids", 74.5, 1)])  # +6,4 %
        self.assertEqual(titres(a, "attention"), ["Variation de poids importante"])
        self.assertIn("pris 6 %", a.points[0].detail)
        self.assertIn("perdu", self.points([mesure_ad("poids", 80, 20), mesure_ad("poids", 74, 1)]).points[0].detail)
        self.assertEqual(titres(self.points([mesure_ad("poids", 70, 20), mesure_ad("poids", 71, 1)])), [])
        self.assertEqual(titres(self.points([mesure_ad("poids", 70, 1)])), [])  # une seule mesure : pas de variation

    def test_suivi_manquant_pour_hypertension_et_diabete(self):
        a = self.points([], antecedents="Hypertension, diabète")
        self.assertEqual(titres(a, "info"), ["Aucune mesure de tension récente", "Aucune mesure de glycémie récente"])
        self.assertTrue(all(p.action == "mesure_nouvelle" for p in a.points))
        b = self.points([mesure_ad("tension", 120, 60, 80), mesure_ad("glycemie", 0.9, 60)], antecedents="Hypertension, diabète")
        self.assertEqual(titres(b), [])  # des mesures datant de deux mois suffisent

    def test_plusieurs_alertes_se_cumulent(self):
        a = self.points([mesure_ad("tension", 190, 1, 110), mesure_ad("saturation", 85, 1), mesure_ad("glycemie", 1.4, 1)])
        self.assertEqual(len(a.importants), 2)
        self.assertEqual(len(a.attentions), 1)


class AnalyseAssemblageTests(SimpleTestCase):
    def test_dossier_complet_et_sans_probleme_est_calme(self):
        a = analyser_cas(mesures=[mesure_ad("tension", 120, valeur2=80)])
        self.assertEqual((a.vigilance, a.points, a.completude), ("calme", [], 100))
        self.assertIn("Rien d'inquiétant", a.message)

    def test_vigilance_prend_la_gravite_la_plus_haute(self):
        self.assertEqual(analyser_cas(mesures=[mesure_ad("tension", 150, valeur2=95)]).vigilance, "a_surveiller")
        self.assertEqual(analyser_cas(mesures=[mesure_ad("tension", 150, valeur2=95), mesure_ad("saturation", 80)]).vigilance, "important")
        self.assertEqual(analyser_cas(manquants=["Groupe sanguin"]).vigilance, "calme")  # une information manquante n'est pas inquiétante

    def test_completude(self):
        a = analyser_cas(manquants=["Groupe sanguin", "Traitements en cours"], total_controles=4)
        self.assertEqual((a.completude, a.manquants), (50, ["Groupe sanguin", "Traitements en cours"]))
        self.assertIn("Des informations utiles manquent", titres(a, "info"))
        self.assertIn("groupe sanguin, traitements en cours", a.points[0].detail)
        self.assertEqual(analyser_cas(total_controles=0).completude, 100)

    def test_aucune_allergie_invite_a_verifier(self):
        a = analyser_cas(allergies=[])
        self.assertIn("Aucune allergie enregistrée", titres(a, "info"))
        self.assertEqual(next(p for p in a.points if "allergie" in p.titre).action, "allergies")
        self.assertNotIn("Aucune allergie enregistrée", titres(analyser_cas(allergies=[allergie_ad()])))

    def test_tri_par_gravite_puis_ordre_des_regles(self):
        a = analyser_cas(allergies=[], manquants=["Groupe sanguin"], mesures=[mesure_ad("tension", 150, valeur2=95), mesure_ad("saturation", 80)])
        self.assertEqual([p.gravite for p in a.points], ["important", "attention", "info", "info"])

    def test_chaque_remarque_est_expliquee(self):
        a = analyser_cas(
            allergies=[allergie_ad("Pénicilline")], traitements="Amoxicilline, Previscan, ibuprofène, Ventoline", antecedents="",
            manquants=["Groupe sanguin"], mesures=[mesure_ad("tension", 190, 1, 112), mesure_ad("glycemie", 1.4), mesure_ad("temperature", 39),
                                                    mesure_ad("poids", 60, 20), mesure_ad("poids", 70, 1)])
        self.assertGreaterEqual(len(a.points), 7)
        for p in a.points:
            with self.subTest(titre=p.titre):
                self.assertTrue(p.detail.strip() and p.pourquoi.strip())  # jamais une boîte noire

    def test_resume(self):
        a = analyser_cas(allergies=[allergie_ad("Pénicilline")], antecedents="Asthme", traitements="Ventoline",
                         mesures=[mesure_ad("tension", 120, valeur2=80), mesure_ad("poids", 70.5)])
        self.assertEqual(a.resume, "Femme de 35 ans · groupe sanguin O+ · allergie sévère à Pénicilline · antécédents repérés : asthme · "
                                   "1 type de traitement reconnu · dernières mesures : tension 120/80 mmHg, poids 70.5 kg.")
        self.assertTrue(analyser_cas(sexe="H", age=60).resume.startswith("Homme de 60 ans"))

    def test_resume_pluriels_et_valeurs_absentes(self):
        a = analyser_cas(groupe_sanguin="", allergies=[allergie_ad("A", "legere"), allergie_ad("B", "legere")], antecedents="", traitements="Ventoline, metformine")
        self.assertIn("2 allergies enregistrées", a.resume)
        self.assertIn("2 types de traitement reconnus", a.resume)
        self.assertNotIn("groupe sanguin", a.resume)
        self.assertNotIn("dernières mesures", a.resume)

    def test_profil_et_ce_que_l_analyse_a_lu(self):
        a = analyser_cas(antecedents="Asthme, hypertension", traitements="Ventoline", mesures=[mesure_ad("poids", 70, 2), mesure_ad("poids", 71, 50)])
        self.assertEqual(a.profil, ["asthme", "hypertension"])
        self.assertEqual(a.lu, {"antecedents": 2, "traitements": 1, "allergies": 1, "mesures": 1})  # une seule mesure date du dernier mois

    def test_l_analyse_ne_pose_jamais_de_diagnostic(self):
        a = analyser_cas(antecedents="", traitements="Metformine", mesures=[mesure_ad("glycemie", 2.5), mesure_ad("tension", 190, valeur2=115)])
        texte = " ".join(p.titre + " " + p.detail for p in a.points).lower()
        for interdit in ("vous avez un diabète", "vous êtes diabétique", "vous souffrez", "diagnostic", "vous avez de l'hypertension"):
            self.assertNotIn(interdit, texte)

    def test_les_urgences_sont_citees_pour_les_alertes_graves(self):
        a = analyser_cas(mesures=[mesure_ad("tension", 190, valeur2=115)])
        self.assertIn("190", a.importants[0].detail)  # numéro d'urgence cité en cas de tension très élevée


class AnalyseServiceEtPagesTests(SimpleTestCase):
    def requete(self, nom="analyse_dossier"):
        requete = RequestFactory().get("/patients/dossier/analyse/")
        requete.user = SimpleNamespace(is_authenticated=True, patient=True, first_name="A", username="a", get_full_name=lambda: "A")
        requete.resolver_match = SimpleNamespace(url_name=nom)
        return requete

    def appeler_la_vue(self, analyse):
        with mock.patch.object(vues_patients, "_patient_connecte", return_value=un_patient()), \
                mock.patch.object(analyse_service, "analyser_patient", return_value=analyse):
            return vues_patients.analyse(self.requete()).content.decode()

    def cas_riche(self):
        return analyser_cas(allergies=[allergie_ad("Pénicilline")], traitements="Amoxicilline, Ventoline", antecedents="",
                            manquants=["Groupe sanguin"], mesures=[mesure_ad("tension", 190, 1, 112), mesure_ad("glycemie", 1.4)])

    def test_adresse_et_acces(self):
        self.assertEqual(reverse("patients:analyse_dossier"), "/patients/dossier/analyse/")
        self.assertIs(resolve("/patients/dossier/analyse/").func, vues_patients.analyse)
        reponse = self.client.get("/patients/dossier/analyse/")
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/comptes/connexion/"))
        requete = RequestFactory().get("/x/")
        requete.user = get_user_model()(username="medecin", role="medecin", is_active=True)
        with self.assertRaises(PermissionDenied):
            vues_patients.analyse(requete)

    def test_page_avec_remarques_expliquees_et_actions(self):
        html = self.appeler_la_vue(self.cas_riche())
        for texte in ("Analyse de mon dossier", "Niveau de vigilance", ">Important<", "Pourquoi cette remarque ?", "Traitement et allergie de la même famille",
                      "Tension très élevée", "Glycémie élevée", "Un antécédent semble manquer (asthme)", "Prendre rendez-vous", "Compléter mon dossier",
                      "Résumé", "Femme de 35 ans", "Ce que l'analyse a lu", "Mesures du mois", "règles médicales simples", "aucun service externe",
                      "ne remplace pas un médecin", "190, le 15 ou le 112"):
            self.assertIn(texte, html)
        self.assertEqual(html.count("<details"), 5)  # une explication « pourquoi » par remarque

    def test_groupes_dans_l_ordre_de_gravite(self):
        html = self.appeler_la_vue(self.cas_riche())
        self.assertLess(html.index(">Important <"), html.index("À surveiller <"))
        self.assertLess(html.index("À surveiller <"), html.index("Pour compléter ou vérifier"))

    def test_boutons_d_action_pointent_vers_les_bonnes_pages(self):
        html = self.appeler_la_vue(self.cas_riche())
        self.assertIn('href="/patients/medecins/"', html)
        self.assertIn('href="/patients/profil/"', html)

    def test_dossier_calme(self):
        html = self.appeler_la_vue(analyser_cas())
        self.assertIn(">Calme<", html)
        self.assertIn("Aucune remarque", html)
        self.assertNotIn("Pourquoi cette remarque", html)
        self.assertNotIn("Prendre rendez-vous", html)  # pas de rendez-vous suggéré quand tout est calme
        self.assertIn("Rien d&#x27;inquiétant", html)

    def test_dossier_a_surveiller(self):
        html = self.appeler_la_vue(analyser_cas(mesures=[mesure_ad("tension", 150, valeur2=95)]))
        self.assertIn(">À surveiller<", html)
        self.assertIn("vigilance-a_surveiller", html)

    def test_completude_affichee_et_accessible(self):
        html = self.appeler_la_vue(analyser_cas(manquants=["Groupe sanguin", "Traitements en cours"]))
        self.assertIn("Dossier rempli à 50 %", html)
        self.assertIn('role="progressbar"', html)
        self.assertIn('aria-valuenow="50"', html)
        self.assertIn("Il manque : groupe sanguin, traitements en cours.", html)

    def test_le_menu_marque_mon_dossier(self):
        html = self.appeler_la_vue(analyser_cas())
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_antecedents_repares_affiches_en_etiquettes(self):
        html = self.appeler_la_vue(analyser_cas(antecedents="Asthme, hypertension"))
        self.assertIn('<li class="tag">asthme</li>', html)
        self.assertIn('<li class="tag">hypertension</li>', html)

    def test_carte_sur_la_page_dossier(self):
        patient_page = DossierPageTests.page
        self.assertTrue(callable(patient_page))
        html = render_to_string("patients/dossier.html", {
            "patient": un_patient_complet(), "dossier": un_dossier(), "allergies": [], "severes": [], "mesures": [], "derniere_demande": None,
            "manquants": [], "analyse": analyser_cas(mesures=[mesure_ad("tension", 190, 1, 112)])}, self.requete("dossier"))
        self.assertIn("Analyse automatique de mon dossier", html)
        self.assertIn('href="/patients/dossier/analyse/"', html)
        self.assertIn(">Important<", html)
        self.assertIn("1 remarque.", html)
        calme = render_to_string("patients/dossier.html", {
            "patient": un_patient_complet(), "dossier": un_dossier(), "allergies": [], "severes": [], "mesures": [], "derniere_demande": None,
            "manquants": [], "analyse": analyser_cas()}, self.requete("dossier"))
        self.assertIn(">Calme<", calme)
        self.assertNotIn("remarque", calme.split("Analyse automatique de mon dossier")[1].split("</section>")[0].replace("Voir l'analyse", ""))

    def test_service_assemble_les_donnees_du_patient(self):
        patient = un_patient_complet()
        fiche = un_dossier(antecedents="Asthme", traitements_en_cours="Amoxicilline")
        allergie = Allergie(patient=patient, substance="Pénicilline", gravite="severe", active=True)
        mesure = Mesure(patient=patient, type="tension", valeur=190, valeur2=112, mesure_le=timezone.now() - datetime.timedelta(days=1))
        faux_dossiers = mock.Mock()
        faux_dossiers.first.return_value = fiche
        with mock.patch.object(DossierMedical.objects, "filter", return_value=faux_dossiers), \
                mock.patch.object(Allergie.objects, "filter", return_value=[allergie]), \
                mock.patch.object(Mesure.objects, "filter", return_value=[mesure]):
            analyse = analyse_service.analyser_patient(patient)
        self.assertEqual(analyse.vigilance, "important")
        self.assertIn("Traitement et allergie de la même famille", titres(analyse))
        self.assertIn("Tension très élevée", titres(analyse))
        self.assertEqual(analyse.profil, ["asthme"])
        self.assertIn("Femme de", analyse.resume)

    def test_service_sans_dossier(self):
        patient = un_patient_complet()
        faux_dossiers = mock.Mock()
        faux_dossiers.first.return_value = None
        with mock.patch.object(DossierMedical.objects, "filter", return_value=faux_dossiers), \
                mock.patch.object(Allergie.objects, "filter", return_value=[]), \
                mock.patch.object(Mesure.objects, "filter", return_value=[]):
            analyse = analyse_service.analyser_patient(patient)
        self.assertEqual(analyse.completude, 100 - 100 * 3 // 4)  # seul le contact d'urgence est renseigné
        self.assertEqual(analyse.profil, [])

    def test_le_back_office_affiche_l_analyse(self):
        racine = Path(__file__).resolve().parent.parent
        self.assertIn("analyse_service.analyser_patient(patient)", (racine / "backoffice" / "views.py").read_text(encoding="utf-8"))
        gabarit = (racine / "backoffice" / "templates" / "backoffice" / "patient_detail.html").read_text(encoding="utf-8")
        for texte in ("Analyse automatique du dossier", "analyse.importants", "analyse.attentions", "ne remplace pas l'avis du médecin"):
            self.assertIn(texte, gabarit)

    def test_styles_de_l_analyse(self):
        css = (Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")
        for classe in (".vigilance-important", ".vigilance-a_surveiller", ".tag", ".remarque-important", ".remarque-attention"):
            self.assertIn(classe, css)
