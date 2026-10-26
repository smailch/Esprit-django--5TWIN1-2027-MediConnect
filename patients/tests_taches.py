"""Analyse IA du dossier en arrière-plan (Celery) : la page n'attend plus l'IA, elle suit son avancement."""
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from . import analyse_service, ia_client, taches


def une_analyse(statut, disponible=True, consentement=True, contenu=True):
    return SimpleNamespace(ia={"disponible": disponible, "consentement": consentement, "contenu_a_lire": contenu, "statut": statut})


PATIENT = SimpleNamespace(pk="p1")


class AnalyseDiffereeTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def analyser(self, *resultats):
        return mock.patch.object(analyse_service, "analyser_patient", side_effect=list(resultats))

    def test_sans_celery_l_analyse_complete_se_fait_dans_la_requete(self):
        with self.analyser(une_analyse(ia_client.OK)) as analyser:
            _, en_cours = taches.analyse_avec_ia_differee(PATIENT)
        self.assertFalse(en_cours)
        self.assertEqual(analyser.call_args.kwargs["ia"], analyse_service.COMPLET)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_reponse_deja_en_cache_rien_a_lancer(self):
        with self.analyser(une_analyse(ia_client.OK)) as analyser, mock.patch.object(taches.analyser_dossier_ia, "delay") as delay:
            _, en_cours = taches.analyse_avec_ia_differee(PATIENT)
        self.assertFalse(en_cours)
        self.assertEqual(analyser.call_args.kwargs["ia"], analyse_service.CACHE)  # jamais d'appel réseau pendant la requête
        delay.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_pas_d_ia_sans_consentement(self):
        with self.analyser(une_analyse(ia_client.ABSENT, consentement=False)), mock.patch.object(taches.analyser_dossier_ia, "delay") as delay:
            self.assertFalse(taches.analyse_avec_ia_differee(PATIENT)[1])
        delay.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_lancee_une_seule_fois_puis_suivie(self):
        with self.analyser(une_analyse(ia_client.ABSENT), une_analyse(ia_client.ABSENT)), \
                mock.patch.object(taches.analyser_dossier_ia, "delay") as delay:
            self.assertTrue(taches.analyse_avec_ia_differee(PATIENT)[1])
            self.assertTrue(taches.analyse_avec_ia_differee(PATIENT)[1])  # page rechargée pendant l'analyse
        delay.assert_called_once_with("p1")
        self.assertEqual(taches.etat("p1")["etat"], "en_cours")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_un_echec_recent_est_explique_sans_relancer_en_boucle(self):
        with self.analyser(une_analyse(ia_client.ABSENT)), mock.patch.object(taches.analyser_dossier_ia, "delay"):
            taches.analyse_avec_ia_differee(PATIENT)
        with mock.patch("patients.models.Patient.objects") as objets,                 mock.patch.object(analyse_service, "analyser_patient", return_value=une_analyse(ia_client.DELAI)):
            objets.select_related.return_value.filter.return_value.first.return_value = PATIENT
            taches.analyser_dossier_ia("p1")  # le worker : l'IA n'a pas répondu à temps
        self.assertEqual(taches.etat("p1")["statut"], ia_client.DELAI)
        with self.analyser(une_analyse(ia_client.ABSENT)), mock.patch.object(taches.analyser_dossier_ia, "delay") as delay:
            analyse, en_cours = taches.analyse_avec_ia_differee(PATIENT)
        self.assertFalse(en_cours)
        self.assertEqual(analyse.ia["statut"], ia_client.DELAI)
        delay.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_redis_injoignable_analyse_dans_la_requete(self):
        with self.analyser(une_analyse(ia_client.ABSENT), une_analyse(ia_client.OK)) as analyser, \
                mock.patch.object(taches.analyser_dossier_ia, "delay", side_effect=ConnectionError), \
                self.assertLogs("mediconnect.ia", level="WARNING"):
            self.assertFalse(taches.analyse_avec_ia_differee(PATIENT)[1])
        self.assertEqual(analyser.call_args.kwargs["ia"], analyse_service.COMPLET)
        self.assertEqual(taches.etat("p1"), {})

    def test_le_worker_note_la_fin_et_la_duree(self):
        with mock.patch("patients.models.Patient.objects") as objets, \
                mock.patch.object(analyse_service, "analyser_patient", return_value=une_analyse(ia_client.OK)):
            objets.select_related.return_value.filter.return_value.first.return_value = PATIENT
            self.assertEqual(taches.analyser_dossier_ia("p1"), ia_client.OK)
        marque = taches.etat("p1")
        self.assertEqual((marque["etat"], marque["statut"]), ("fini", ia_client.OK))
        self.assertGreaterEqual(marque["duree_ms"], 0)
