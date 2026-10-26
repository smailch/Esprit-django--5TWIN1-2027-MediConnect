"""Tâches de fond (Celery) : e-mails de notification envoyés tout de suite sans Redis, confiés au worker avec Redis."""
from unittest import mock

from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import SimpleTestCase, override_settings

from . import courriel, taches


def un_message():
    message = EmailMultiAlternatives("Rendez-vous confirmé — MediConnect", "Texte", None, ["amel@exemple.tn"])
    message.attach_alternative("<p>HTML</p>", "text/html")
    return message


class EnvoiDiffereTests(SimpleTestCase):
    def test_sans_courtier_l_e_mail_part_tout_de_suite(self):
        mail.outbox = []
        self.assertTrue(courriel.envoyer(un_message(), "essai"))
        self.assertEqual(len(mail.outbox), 1)

    def test_un_echec_est_journalise_jamais_propage(self):
        with mock.patch.object(EmailMultiAlternatives, "send", side_effect=OSError("SMTP en panne")), \
                self.assertLogs("mediconnect.courriel", level="ERROR"):
            self.assertFalse(courriel.envoyer(un_message(), "essai"))

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_avec_courtier_l_e_mail_est_confie_au_worker_en_json(self):
        mail.outbox = []
        with mock.patch.object(taches.envoyer_courriel, "delay") as delay:
            self.assertTrue(courriel.envoyer(un_message(), "rdv 42"))
        self.assertEqual(mail.outbox, [])  # rien n'est parti pendant la requête
        donnees, origine = delay.call_args.args
        self.assertEqual(origine, "rdv 42")
        self.assertEqual(donnees["a"], ["amel@exemple.tn"])
        self.assertEqual(donnees["alternatives"], [["<p>HTML</p>", "text/html"]])

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_redis_injoignable_envoi_direct(self):
        mail.outbox = []
        with mock.patch.object(taches.envoyer_courriel, "delay", side_effect=ConnectionError("redis")), \
                self.assertLogs("mediconnect.courriel", level="WARNING"):
            self.assertTrue(courriel.envoyer(un_message(), "essai"))
        self.assertEqual(len(mail.outbox), 1)

    def test_le_worker_reconstruit_et_envoie_le_message(self):
        mail.outbox = []
        self.assertTrue(taches.envoyer_courriel(courriel.vers_dict(un_message()), "essai"))
        envoye = mail.outbox[0]
        self.assertEqual((envoye.subject, envoye.to, envoye.alternatives[0][1]), ("Rendez-vous confirmé — MediConnect", ["amel@exemple.tn"], "text/html"))

    def test_le_worker_reessaie_si_le_reseau_coupe(self):
        self.assertIn(OSError, taches.envoyer_courriel.autoretry_for)
        self.assertEqual(taches.envoyer_courriel.max_retries, 3)

    def test_configuration_celery(self):
        from django.conf import settings

        from mediconnect.celery import app

        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)  # tests et poste sans REDIS_URL
        self.assertIn("core.taches.envoyer_courriel", app.tasks)
        self.assertIn("patients.taches.analyser_dossier_ia", app.tasks)
        self.assertIn("infirmiers.taches.relire_compte_rendu", app.tasks)
