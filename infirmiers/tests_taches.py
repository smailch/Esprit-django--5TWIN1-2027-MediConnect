"""Relecture IA en arrière-plan d'un compte rendu enregistré pendant une panne de l'IA (Celery)."""
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from core import fabriques_test as f
from patients import ia_client

from . import alertes, taches
from .ia_soin import Analyse
from .models import InterventionDomicile, NiveauAlerte, SigneAlerte


def un_compte_rendu(statut_ia=ia_client.DELAI, niveau=NiveauAlerte.SURVEILLER):
    infirmier = f.un_infirmier()
    intervention = InterventionDomicile.objects.create(
        patient=f.un_patient(), type_soin="pansement", adresse="7 rue de Rome", ville="Tunis",
        date_souhaitee=f.demain().date(), moment="matin",
    )
    intervention.accepter(infirmier, f.demain(9))
    intervention.save()
    intervention.terminer("Plaie rouge et chaude, patient fatigué.", realisee_le=timezone.now(),
                          analyse=Analyse(signes=[alertes.Signe("Rougeur", "rouge", NiveauAlerte.SURVEILLER, alertes.TEXTE)],
                                          niveau=niveau, statut_ia=statut_ia))
    intervention.save()
    return intervention


class ProgrammationTests(TestCase):
    def test_sans_celery_rien_n_est_programme(self):
        with mock.patch.object(taches.relire_compte_rendu, "apply_async") as programmer:
            self.assertFalse(taches.programmer_relecture(un_compte_rendu()))
        programmer.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_panne_passagere_relecture_dans_une_minute(self):
        intervention = un_compte_rendu()
        with mock.patch.object(taches.relire_compte_rendu, "apply_async") as programmer:
            self.assertTrue(taches.programmer_relecture(intervention))
        programmer.assert_called_once_with(args=[str(intervention.pk)], countdown=60)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_ia_desactivee_ou_deja_lue_pas_de_relecture(self):
        for statut in (ia_client.OK, ia_client.NON_CONFIGUREE, ia_client.QUOTA):
            with self.subTest(statut=statut), mock.patch.object(taches.relire_compte_rendu, "apply_async") as programmer:
                self.assertFalse(taches.programmer_relecture(un_compte_rendu(statut_ia=statut)))
                programmer.assert_not_called()


class RelectureTests(TestCase):
    def relire(self, intervention, analyse):
        with mock.patch.object(taches.ia_soin, "analyser", return_value=analyse):
            return taches.relire_compte_rendu.run(str(intervention.pk))

    def test_l_ia_ajoute_un_signe_et_le_niveau_monte(self):
        intervention = un_compte_rendu(niveau=NiveauAlerte.SURVEILLER)
        avant = len(intervention.signes_alerte)
        signe_ia = alertes.Signe("Infection probable", "rouge et chaude", NiveauAlerte.SIGNALER, SigneAlerte.Origine.IA)
        self.assertEqual(self.relire(intervention, Analyse(signes=[signe_ia], niveau=NiveauAlerte.SIGNALER, statut_ia=ia_client.OK)),
                         NiveauAlerte.SIGNALER)
        intervention.refresh_from_db()
        self.assertEqual((intervention.niveau_alerte, intervention.analyse_ia), (NiveauAlerte.SIGNALER, ia_client.OK))
        self.assertEqual(len(intervention.signes_alerte), avant + 1)
        self.assertTrue(intervention.alerte_a_traiter)

    def test_le_niveau_ne_baisse_jamais(self):
        intervention = un_compte_rendu(niveau=NiveauAlerte.SIGNALER)
        self.relire(intervention, Analyse(signes=[], niveau=NiveauAlerte.RAS, statut_ia=ia_client.OK))
        intervention.refresh_from_db()
        self.assertEqual(intervention.niveau_alerte, NiveauAlerte.SIGNALER)

    def test_ia_encore_en_panne_la_tache_reessaie(self):
        intervention = un_compte_rendu()
        with self.assertRaises(taches.IaToujoursIndisponible):
            self.relire(intervention, Analyse(statut_ia=ia_client.RESEAU))
        self.assertIn(taches.IaToujoursIndisponible, taches.relire_compte_rendu.autoretry_for)

    def test_deja_lue_rien_a_faire(self):
        intervention = un_compte_rendu(statut_ia=ia_client.OK)
        with mock.patch.object(taches.ia_soin, "analyser") as analyser:
            self.assertEqual(taches.relire_compte_rendu.run(str(intervention.pk)), "rien à faire")
        analyser.assert_not_called()
