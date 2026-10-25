import json
import random
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

import joblib
from django.apps import apps
from django.core.management import call_command
from django.test import SimpleTestCase

from . import decision, donnees, lexique, modele


class LexiqueTests(SimpleTestCase):
    def test_chaque_unite_est_bien_formee(self):
        catalogue = donnees.catalogue()
        for u in lexique.UNITES:
            with self.subTest(u["formes"][0]):
                self.assertGreater(u["poids"], 0)
                self.assertGreaterEqual(len(u["formes"]), 2)
                for cle in ("symptome", "symptome2"):
                    if cle in u["effet"]:
                        self.assertIn(u["effet"][cle], catalogue)  # un vrai symptôme du catalogue du projet
                if "echelle" in u["effet"]:
                    nom, valeur = u["effet"]["echelle"]
                    self.assertIn(nom, ("douleur", "fievre", "respiration", "etat_general"))
                    self.assertIn(valeur, range(6))
                if "valeurs" in u:  # les formes à température portent le marqueur {t}
                    self.assertTrue(all("{t}" in f for f in u["formes"]))

    def test_il_y_a_des_cas_graves_courants_et_sans_symptome(self):
        effets = [u["effet"] for u in lexique.UNITES]
        self.assertTrue(any(e.get("symptome") == "Douleur thoracique" for e in effets))
        self.assertTrue(any(e == {} for e in effets))


class DonneesTests(SimpleTestCase):
    def test_niveau_calcule_par_les_regles_du_projet(self):
        cas = (
            ([], 5),
            ([{"symptome": "Douleur thoracique"}], 1),
            ([{"symptome": "Convulsions"}], 2),
            ([{"symptome": "Toux"}], 5),  # un symptôme courant isolé : pas d'urgence
            ([{"symptome": "Toux"}, {"symptome": "Mal de gorge"}, {"symptome": "Maux de tête"}], 4),
            ([{"temperature": 41.5}], 2),
            ([{"echelle": ("respiration", 5)}], 1),
            ([{"echelle": ("douleur", 5)}], 2),
        )
        for effets, attendu in cas:
            with self.subTest(effets=effets):
                self.assertEqual(donnees.niveau_des_effets(effets), attendu)

    def test_meme_graine_memes_phrases_graine_differente_autres_phrases(self):
        self.assertEqual(donnees.generer(200, 5), donnees.generer(200, 5))
        self.assertNotEqual(donnees.generer(200, 5), donnees.generer(200, 6))

    def test_les_cinq_niveaux_sont_representes(self):
        niveaux = [n for _, n in donnees.generer(3000, 1)]
        for n in range(1, 6):
            with self.subTest(niveau=n):
                self.assertGreater(niveaux.count(n) / len(niveaux), 0.03)  # assez d'exemples de chaque niveau pour apprendre
        self.assertTrue(all(t.strip() for t, _ in donnees.generer(300, 1)))

    def test_le_niveau_d_une_phrase_vient_de_ses_effets(self):
        rng, cat = random.Random(3), donnees.catalogue()
        for _ in range(300):
            texte, niveau, effets = donnees.phrase(rng, cat)
            self.assertEqual(niveau, donnees.niveau_des_effets(effets, cat), texte)

    def test_une_negation_ou_un_proche_ne_compte_pas(self):
        # le jeu contient des phrases avec « pas de fièvre » ou « mon père a eu … » : leur niveau ignore ces morceaux
        rng, cat = random.Random(11), donnees.catalogue()
        vus = 0
        for _ in range(2000):
            texte, niveau, effets = donnees.phrase(rng, cat)
            if not effets and ("mon père" in texte.lower() or "pas de" in texte.lower()):
                self.assertEqual(niveau, 5, texte)
                vus += 1
        self.assertGreater(vus, 5)

    def test_le_bruit_ne_perd_pas_les_lettres(self):
        rng = random.Random(1)
        texte = "j'ai de la fièvre depuis hier"
        faute = donnees._faute_de_frappe(texte, rng)
        self.assertEqual(sorted(faute.replace(" ", "")), sorted(texte.replace(" ", "")))  # deux lettres échangées, rien de perdu
        self.assertEqual(donnees._sans_accents("Éruption à la fièvre"), "Eruption a la fievre")

    def test_phrases_a_la_main(self):
        jeu = dict(donnees.phrases_a_la_main())
        self.assertGreaterEqual(len(jeu), 35)
        self.assertEqual(jeu["Mon père a eu une douleur à la poitrine hier, moi je vais bien"], 5)
        self.assertEqual(jeu["Mon fils a perdu connaissance et il convulse"], 1)
        self.assertEqual(set(jeu.values()) - {1, 2, 3, 4, 5}, set())


class ModeleTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entraine, cls.evaluation = modele.entrainer(n=2500, graine=7, n_test=500)

    def setUp(self):
        modele.installer(self.entraine)  # le modèle du test, jamais celui du disque
        self.addCleanup(modele.oublier)

    def test_prediction(self):
        p = modele.predire("Depuis ce matin quelque chose me serre la poitrine")
        self.assertEqual(set(p), {"niveau", "confiance", "probas", "mots"})
        self.assertIn(p["niveau"], range(1, 6))
        self.assertAlmostEqual(sum(p["probas"].values()), 1, places=2)
        self.assertEqual(p["confiance"], max(p["probas"].values()))
        self.assertLessEqual(p["niveau"], 2)
        self.assertTrue(any("poitrine" in m for m in p["mots"]), p["mots"])  # il explique : « poitrine » a pesé

    def test_graves_et_benins(self):
        for texte in ("je n'arrive plus à respirer", "il fait une crise de convulsions", "je saigne beaucoup et ça ne s'arrête pas"):
            with self.subTest(texte=texte):
                self.assertLessEqual(modele.predire(texte)["niveau"], 2)
        for texte in ("je voudrais renouveler mon ordonnance", "un simple contrôle de routine", "pas de fièvre, pas de toux, juste un bilan"):
            with self.subTest(texte=texte):
                self.assertGreaterEqual(modele.predire(texte)["niveau"], 4)

    def test_faute_de_frappe_et_accents(self):
        self.assertLessEqual(modele.predire("je n'arive plus a respirer")["niveau"], 2)

    def test_texte_vide_ou_modele_absent(self):
        for texte in ("", "   ", None):
            self.assertIsNone(modele.predire(texte))
        modele.oublier()
        with mock.patch.object(modele, "charger", return_value=None):
            self.assertIsNone(modele.predire("j'ai mal"))

    def test_une_panne_de_prediction_ne_remonte_pas(self):
        faux = mock.Mock()
        faux.predict_proba.side_effect = RuntimeError("panne")
        modele.installer(faux)
        with self.assertLogs("mediconnect.ia", level="ERROR"):
            self.assertIsNone(modele.predire("j'ai mal à la poitrine"))

    def test_evaluation(self):
        for cle in ("test_genere", "test_a_la_main"):
            e = self.evaluation[cle]
            with self.subTest(cle=cle):
                self.assertEqual(sum(map(sum, e["matrice"])), e["n"])
                self.assertEqual(len(e["matrice"]), 5)
                for k in ("precision", "a_un_niveau_pres", "reference_toujours_la_meme_reponse"):
                    self.assertTrue(0 <= e[k] <= 1)
        g = self.evaluation["test_genere"]
        self.assertGreater(g["precision"], g["reference_toujours_la_meme_reponse"] + 0.3)  # il apprend vraiment quelque chose
        self.assertGreater(g["graves_reperes"], 0.9)
        self.assertLess(g["fausses_alertes"], 0.05)
        self.assertEqual(self.evaluation["n_entrainement"], 2500)

    def test_mots_par_niveau(self):
        mots = self.evaluation["mots_par_niveau"]
        self.assertEqual(sorted(mots), ["1", "2", "3", "4", "5"])
        self.assertTrue(all(len(v) == 8 for v in mots.values()))

    def test_sauvegarde_et_rechargement(self):
        with tempfile.TemporaryDirectory() as dossier:
            modele.sauvegarder(self.entraine, self.evaluation, dossier)
            recharge = joblib.load(Path(dossier) / modele.NOM_MODELE)
            texte = ["je n'arrive plus à respirer", "un contrôle de routine"]
            self.assertEqual(list(recharge.predict(texte)), list(self.entraine.predict(texte)))
            self.assertEqual(modele.charger_evaluation(dossier), json.loads(json.dumps(self.evaluation)))
            self.assertLess((Path(dossier) / modele.NOM_MODELE).stat().st_size, 5_000_000)  # quelques Mo au plus
        self.assertIsNone(modele.charger_evaluation("/dossier/inexistant"))

    def test_chargement_depuis_le_disque(self):
        with tempfile.TemporaryDirectory() as dossier:
            modele.sauvegarder(self.entraine, self.evaluation, dossier)
            modele.oublier()
            with mock.patch.object(modele, "DOSSIER_ARTEFACTS", Path(dossier)), mock.patch.object(modele, "entrainer") as entrainement:
                self.assertIsNotNone(modele.charger())
                entrainement.assert_not_called()  # le fichier existe : aucun réentraînement

    def test_modele_absent_il_est_entraine_une_fois_puis_enregistre(self):
        with tempfile.TemporaryDirectory() as dossier:
            modele.oublier()
            with mock.patch.object(modele, "DOSSIER_ARTEFACTS", Path(dossier)), \
                    mock.patch.object(modele, "entrainer", return_value=(self.entraine, self.evaluation)) as entrainement:
                self.assertIs(modele.charger(), self.entraine)
                self.assertIs(modele.charger(), self.entraine)
                entrainement.assert_called_once()
            self.assertTrue((Path(dossier) / modele.NOM_MODELE).exists())

    def test_modele_inutilisable_le_triage_continue(self):
        with tempfile.TemporaryDirectory() as dossier:
            modele.oublier()
            with mock.patch.object(modele, "DOSSIER_ARTEFACTS", Path(dossier)), \
                    mock.patch.object(modele, "entrainer", side_effect=RuntimeError("disque plein")) as entrainement:
                with self.assertLogs("mediconnect.ia", level="ERROR"):
                    self.assertIsNone(modele.charger())
                self.assertIsNone(modele.predire("j'ai mal"))
                entrainement.assert_called_once()  # pas de nouvel essai à chaque demande


class DecisionTests(SimpleTestCase):
    def pred(self, niveau, confiance):
        return {"niveau": niveau, "confiance": confiance, "probas": {}, "mots": ["poitrine"]}

    def test_il_ne_fait_que_relever(self):
        self.assertEqual(decision.relever(4, self.pred(2, 0.95)), (2, True))
        self.assertEqual(decision.relever(5, self.pred(3, 0.90)), (3, True))
        for niveau_regles, predit in ((2, 4), (3, 5), (3, 3), (5, 5)):
            with self.subTest(regles=niveau_regles, modele=predit):
                self.assertEqual(decision.relever(niveau_regles, self.pred(predit, 0.99)), (niveau_regles, False))  # jamais de baisse

    def test_le_niveau_vital_reste_aux_regles_et_au_medecin(self):
        self.assertEqual(decision.relever(4, self.pred(1, 0.99)), (2, True))  # plafonné au niveau 2
        self.assertEqual(decision.relever(2, self.pred(1, 0.99)), (2, False))

    def test_seuil_de_confiance(self):
        self.assertEqual(decision.relever(4, self.pred(2, 0.84)), (4, False))
        self.assertEqual(decision.relever(4, self.pred(2, 0.85)), (2, True))
        self.assertEqual(decision.relever(4, self.pred(2, 0.60), seuil=0.5), (2, True))
        self.assertEqual(decision.relever(4, self.pred(2, 0.60), seuil=0.9), (4, False))
        self.assertEqual(decision.SEUIL_PAR_DEFAUT, 0.85)

    def test_sans_avis_rien_ne_change(self):
        self.assertEqual(decision.relever(4, None), (4, False))
        self.assertEqual(decision.relever(None, self.pred(2, 0.99)), (None, False))

    def test_phrase_explicative(self):
        texte = decision.phrase_explicative(self.pred(2, 0.912), 2)
        for morceau in ("niveau 2", "91 % de confiance", "« poitrine »", "relevé à 2", "à confirmer par le médecin"):
            self.assertIn(morceau, texte)
        self.assertNotIn("à cause de", decision.phrase_explicative({"niveau": 2, "confiance": 0.9, "mots": []}, 2))


class CommandeTests(SimpleTestCase):
    def test_entrainer_triage(self):
        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(modele, "DOSSIER_ARTEFACTS", Path(dossier)):
            self.addCleanup(modele.oublier)
            sortie = StringIO()
            call_command("entrainer_triage", "--n", "600", "--graine", "3", stdout=sortie)
            texte = sortie.getvalue()
            for morceau in ("600 phrases d'entraînement", "niveau exact", "cas graves repérés", "fausses alertes", "Modèle enregistré"):
                self.assertIn(morceau, texte)
            self.assertTrue((Path(dossier) / modele.NOM_MODELE).exists())
            self.assertEqual(modele.charger_evaluation(dossier)["n_entrainement"], 600)


class ApplicationTests(SimpleTestCase):
    def test_l_application_est_installee(self):
        self.assertTrue(apps.is_installed("ia"))

    def test_scikit_learn_est_dans_les_dependances(self):
        exigences = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("scikit-learn", exigences)
