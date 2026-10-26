"""Évaluation de la détection des signes d'alerte : calcul des métriques et non-régression des règles."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from . import evaluation, ia_soin


class MetriquesTests(SimpleTestCase):
    def test_calcul_sur_un_exemple_connu(self):
        vrais = ["ras", "ras", "surveiller", "signaler", "signaler"]
        predits = ["ras", "signaler", "surveiller", "ras", "signaler"]
        m = evaluation.metriques(vrais, predits)
        self.assertEqual(m["matrice"]["valeurs"], [[1, 0, 1], [0, 1, 0], [1, 0, 1]])
        self.assertEqual(m["exactitude"], 0.6)
        self.assertEqual(m["par_niveau"]["signaler"], {"precision": 0.5, "rappel": 0.5, "f1": 0.5, "support": 2})
        self.assertEqual((m["alertes_manquees"], m["fausses_alertes"]), (1, 1))

    def test_retente_apres_une_limite_et_mesure_le_dernier_appel(self):
        reponses = iter([SimpleNamespace(niveau="ras", statut_ia="limite"), SimpleNamespace(niveau="signaler", statut_ia="ok")])
        r = evaluation.evaluer([{"texte": "x", "attendu": "signaler"}], lambda texte, ia: next(reponses), avec_ia=True)
        self.assertEqual((r["statuts_ia"], r["exactitude"]), ({"ok": 1}, 1.0))
        self.assertIn("p95", r["temps_ms"])

    def test_corpus_equilibre(self):
        notes = evaluation.charger()
        self.assertEqual(len(notes), 60)
        self.assertEqual({n["attendu"] for n in notes}, set(evaluation.NIVEAUX))
        self.assertEqual(sorted(sum(1 for n in notes if n["attendu"] == niveau) for niveau in evaluation.NIVEAUX), [20, 20, 20])


class NonRegressionDesReglesTests(SimpleTestCase):
    """Les règles seules (sans IA, sans réseau) ne doivent jamais faire moins bien que la mesure de référence."""

    def setUp(self):
        self.r = evaluation.evaluer(evaluation.charger(), lambda texte, ia: ia_soin.analyser(texte, utiliser_ia=False))

    def test_aucune_fausse_alerte(self):
        self.assertEqual(self.r["fausses_alertes"], 0)
        self.assertEqual(self.r["par_niveau"]["signaler"]["precision"], 1.0)

    def test_au_moins_la_moitie_des_cas_graves_reperes(self):
        self.assertGreaterEqual(self.r["par_niveau"]["signaler"]["rappel"], 0.5)
        self.assertGreaterEqual(self.r["f1_macro"], 0.6)
