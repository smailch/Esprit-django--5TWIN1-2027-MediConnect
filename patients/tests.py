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
