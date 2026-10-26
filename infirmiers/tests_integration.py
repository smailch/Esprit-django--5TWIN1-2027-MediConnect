"""Tests d'intégration du module soins à domicile : vraie base (MongoDB de test) et client HTTP de Django.

CRUD complet des deux entités (Infirmier, InterventionDomicile) par les pages, et le parcours de bout en bout :
le patient demande -> l'infirmier de la zone accepte -> il saisit le compte rendu -> les constantes rejoignent le
dossier du patient -> l'administrateur traite l'alerte. Les e-mails partent dans la boîte de test (mail.outbox).
"""
import datetime

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from core import fabriques_test as f
from core.models import User
from patients.models import Mesure

from .forms import FORMAT_DATE_HEURE
from .models import Infirmier, InterventionDomicile, NiveauAlerte

Statut = InterventionDomicile.Statut


def demande_de(patient, **kw):
    valeurs = dict(patient=patient, type_soin="injection", description="Anticoagulant", adresse="7 rue de Rome",
                   ville="Tunis", date_souhaitee=f.demain().date(), moment="matin")
    valeurs.update(kw)
    return InterventionDomicile.objects.create(**valeurs)


@override_settings(IA_FOURNISSEUR="aucun")  # les règles seules : aucun appel réseau pendant les tests
class InfirmierCrudTests(TestCase):
    def test_inscription_cree_le_compte_en_attente_de_validation(self):
        reponse = self.client.post("/infirmiers/inscription/", {
            "username": "nadia", "first_name": "Nadia", "last_name": "Ben Ali", "email": "nadia@exemple.tn",
            "password1": f.MOT_DE_PASSE, "password2": f.MOT_DE_PASSE, "telephone": "22 333 444",
            "numero_ordre": "TN-12345", "ville": "Ariana", "zones": "Tunis, La Marsa", "soins": ["injection", "pansement"],
        })
        self.assertRedirects(reponse, "/infirmiers/tableau-de-bord/")
        infirmier = Infirmier.objects.select_related("user").get(user__username="nadia")
        self.assertEqual((infirmier.user.role, infirmier.user.est_valide), (User.Role.INFIRMIER, False))
        self.assertEqual((infirmier.ville, infirmier.zones, infirmier.soins), ("Ariana", ["Tunis", "La Marsa"], ["injection", "pansement"]))
        self.assertTrue(infirmier.user.check_password(f.MOT_DE_PASSE))
        self.assertContains(self.client.get("/infirmiers/tableau-de-bord/"), "valid")

    def test_inscription_invalide_reaffiche_les_erreurs(self):
        f.un_infirmier("sami")
        reponse = self.client.post("/infirmiers/inscription/", {"username": "sami", "password1": "a", "password2": "b"})
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["form"].errors)
        self.assertEqual(Infirmier.objects.count(), 1)

    def test_lecture_et_modification_du_profil(self):
        infirmier = f.un_infirmier("sami")
        self.client.force_login(infirmier.user)
        self.assertContains(self.client.get("/infirmiers/profil/"), "ORD-")
        reponse = self.client.post("/infirmiers/profil/", {
            "first_name": "Sami", "last_name": "Trabelsi", "email": "sami@exemple.tn", "telephone": "98 765 432",
            "ville": "Tunis", "zones": "Ariana", "soins": ["prelevement"], "disponible": "",
        })
        self.assertRedirects(reponse, "/infirmiers/profil/")
        infirmier.refresh_from_db()
        self.assertEqual((infirmier.zones, infirmier.soins, infirmier.disponible), (["Ariana"], ["prelevement"], False))

    def test_desactivation_par_l_administrateur(self):
        infirmier = f.un_infirmier("sami")
        self.client.force_login(f.un_admin())
        self.client.post(f"/backoffice/comptes/{infirmier.user.pk}/desactiver/")
        self.client.logout()
        self.assertFalse(self.client.login(username="sami", password=f.MOT_DE_PASSE))


@override_settings(IA_FOURNISSEUR="aucun")
class DemandeDeSoinCrudTests(TestCase):
    def setUp(self):
        self.patient = f.un_patient("amel")
        self.client.force_login(self.patient.user)

    def donnees(self, **kw):
        valeurs = {"type_soin": "pansement", "description": "Plaie au genou", "date_souhaitee": f.demain().date().isoformat(),
                   "moment": "matin", "adresse": "7 rue de Rome", "ville": "Tunis", "repetition": "", "nombre_passages": ""}
        valeurs.update(kw)
        return valeurs

    def test_creer_lire_modifier_supprimer(self):
        reponse = self.client.post("/infirmiers/soins/nouveau/", self.donnees())
        demande = InterventionDomicile.objects.get()
        self.assertRedirects(reponse, f"/infirmiers/soins/{demande.pk}/")
        self.assertEqual((demande.patient, demande.statut, demande.type_soin), (self.patient, Statut.DEMANDEE, "pansement"))
        self.assertContains(self.client.get("/infirmiers/soins/"), "Pansement")
        self.assertContains(self.client.get(f"/infirmiers/soins/{demande.pk}/"), "Plaie au genou")

        self.client.post(f"/infirmiers/soins/{demande.pk}/modifier/", self.donnees(description="Plaie au coude", moment="apres_midi"))
        demande.refresh_from_db()
        self.assertEqual((demande.description, demande.moment), ("Plaie au coude", "apres_midi"))

        self.assertEqual(self.client.get(f"/infirmiers/soins/{demande.pk}/supprimer/").status_code, 200)  # confirmation
        self.assertRedirects(self.client.post(f"/infirmiers/soins/{demande.pk}/supprimer/"), "/infirmiers/soins/")
        self.assertFalse(InterventionDomicile.objects.exists())

    def test_serie_de_soins_repetes(self):
        self.client.post("/infirmiers/soins/nouveau/", self.donnees(type_soin="injection", repetition="1", nombre_passages="5"))
        serie = list(InterventionDomicile.objects.order_by("rang_serie"))
        self.assertEqual([d.rang_serie for d in serie], [1, 2, 3, 4, 5])
        self.assertEqual(len({d.serie for d in serie}), 1)
        self.assertEqual(serie[-1].date_souhaitee - serie[0].date_souhaitee, datetime.timedelta(days=4))

    def test_validation_cote_serveur(self):
        hier = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        reponse = self.client.post("/infirmiers/soins/nouveau/", self.donnees(date_souhaitee=hier, ville=""))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("date_souhaitee", reponse.context["form"].errors)
        self.assertIn("ville", reponse.context["form"].errors)
        self.assertFalse(InterventionDomicile.objects.exists())

    def test_une_demande_acceptee_ne_se_modifie_plus(self):
        demande = demande_de(self.patient)
        demande.accepter(f.un_infirmier(), f.demain(10))
        demande.save()
        self.assertRedirects(self.client.post(f"/infirmiers/soins/{demande.pk}/modifier/", self.donnees()), f"/infirmiers/soins/{demande.pk}/")
        self.client.post(f"/infirmiers/soins/{demande.pk}/supprimer/")
        self.assertTrue(InterventionDomicile.objects.filter(pk=demande.pk).exists())

    def test_la_demande_d_un_autre_patient_est_introuvable(self):
        autre = demande_de(f.un_patient())
        for url in (f"/infirmiers/soins/{autre.pk}/", f"/infirmiers/soins/{autre.pk}/modifier/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(f"/infirmiers/soins/{autre.pk}/supprimer/").status_code, 404)


@override_settings(IA_FOURNISSEUR="aucun")
class ParcoursCompletTests(TestCase):
    """Patient -> infirmier -> compte rendu -> dossier du patient -> alerte traitée par l'administrateur."""

    def test_de_la_demande_au_traitement_de_l_alerte(self):
        patient = f.un_patient("amel", ville="Ariana")
        infirmier = f.un_infirmier("sami", ville="Tunis", zones=["Ariana"])
        hors_zone = f.un_infirmier("ines", ville="Sfax")
        demande = demande_de(patient, ville="Ariana")
        mail.outbox = []

        # l'infirmier hors zone ne voit pas la demande ; celui de la zone la voit et l'accepte
        self.client.force_login(hors_zone.user)
        visibles = [ligne["premier"] for ligne in self.client.get("/infirmiers/demandes/").context["demandes"]]
        self.assertNotIn(demande, visibles)
        self.client.force_login(infirmier.user)
        self.assertContains(self.client.get("/infirmiers/demandes/"), "Injection")
        passage = f.demain(9, 30)
        reponse = self.client.post(f"/infirmiers/interventions/{demande.pk}/accepter/",
                                   {"date_prevue": timezone.localtime(passage).strftime(FORMAT_DATE_HEURE)})
        self.assertRedirects(reponse, f"/infirmiers/interventions/{demande.pk}/")
        demande.refresh_from_db()
        self.assertEqual((demande.statut, demande.infirmier, demande.date_prevue), (Statut.ACCEPTEE, infirmier, passage))
        self.assertEqual([m.to for m in mail.outbox], [[patient.user.email]])  # le patient est prévenu
        self.assertContains(self.client.get("/infirmiers/planning/"), "Amel")

        # compte rendu avec des signes d'alerte : fièvre + saturation basse
        realise = timezone.localtime().replace(second=0, microsecond=0)
        reponse = self.client.post(f"/infirmiers/interventions/{demande.pk}/compte-rendu/", {
            "compte_rendu": "Injection faite. Patiente essoufflée, frissons.", "realisee_le": realise.strftime(FORMAT_DATE_HEURE),
            "temperature": "39.4", "saturation_oxygene": "89",
        })
        self.assertRedirects(reponse, f"/infirmiers/interventions/{demande.pk}/")
        demande.refresh_from_db()
        self.assertEqual((demande.statut, demande.niveau_alerte), (Statut.REALISEE, NiveauAlerte.SIGNALER))
        self.assertTrue(demande.alerte_a_traiter)
        # les constantes rejoignent « Mes mesures » du patient
        releves = dict(Mesure.objects.filter(patient=patient).values_list("type", "valeur"))
        self.assertEqual(releves, {"temperature": 39.4, "saturation": 89})

        # l'administrateur voit l'alerte et la traite
        self.client.force_login(f.un_admin())
        self.assertContains(self.client.get("/infirmiers/alertes/"), "Amel")
        self.client.post(f"/infirmiers/alertes/{demande.pk}/traiter/", {"suite": "Médecin traitant prévenu."})
        demande.refresh_from_db()
        self.assertEqual(demande.alerte_suite, "Médecin traitant prévenu.")
        self.assertFalse(demande.alerte_a_traiter)

        # le patient lit le compte rendu et la suite donnée
        self.client.force_login(patient.user)
        page = self.client.get(f"/infirmiers/soins/{demande.pk}/")
        self.assertContains(page, "Injection faite")

    def test_un_compte_non_valide_ne_peut_pas_accepter(self):
        patient = f.un_patient()
        demande = demande_de(patient)
        infirmier = f.un_infirmier(est_valide=False)
        self.client.force_login(infirmier.user)
        self.client.post(f"/infirmiers/interventions/{demande.pk}/accepter/",
                         {"date_prevue": timezone.localtime(f.demain(10)).strftime(FORMAT_DATE_HEURE)})
        demande.refresh_from_db()
        self.assertEqual(demande.statut, Statut.DEMANDEE)


@override_settings(IA_FOURNISSEUR="aucun")
class OrganisationDeLInfirmierTests(TestCase):
    """Série acceptée en bloc, conflits de planning, déplacement, désistement, annulation, tournée et historique."""

    def setUp(self):
        self.infirmier = f.un_infirmier("sami", ville="Tunis", zones=["Ariana"])
        self.patient = f.un_patient("amel")
        self.client.force_login(self.infirmier.user)
        mail.outbox = []

    def accepter(self, demande, quand):
        return self.client.post(f"/infirmiers/interventions/{demande.pk}/accepter/",
                                {"date_prevue": timezone.localtime(quand).strftime(FORMAT_DATE_HEURE)})

    def test_serie_acceptee_en_bloc_avec_un_seul_e_mail(self):
        cle = "serie-test"
        passages = [demande_de(self.patient, serie=cle, rang_serie=i + 1, taille_serie=3,
                               date_souhaitee=f.demain().date() + datetime.timedelta(days=i)) for i in range(3)]
        self.assertContains(self.client.get(f"/infirmiers/series/{cle}/"), "3")
        self.assertRedirects(self.client.post(f"/infirmiers/series/{cle}/", {"heure": "08:00"}), "/infirmiers/planning/")
        for passage in passages:
            passage.refresh_from_db()
            self.assertEqual((passage.statut, timezone.localtime(passage.date_prevue).hour), (Statut.ACCEPTEE, 8))
        self.assertEqual(len(mail.outbox), 1)

    def test_deux_passages_trop_proches_refuses(self):
        premier, second = demande_de(self.patient), demande_de(f.un_patient())
        self.accepter(premier, f.demain(9))
        reponse = self.accepter(second, f.demain(9, 15))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["form"].errors)
        second.refresh_from_db()
        self.assertEqual(second.statut, Statut.DEMANDEE)

    def test_deplacer_se_desister_et_annuler(self):
        demande = demande_de(self.patient)
        self.accepter(demande, f.demain(9))
        self.client.post(f"/infirmiers/interventions/{demande.pk}/replanifier/",
                         {"date_prevue": timezone.localtime(f.demain(15)).strftime(FORMAT_DATE_HEURE)})
        demande.refresh_from_db()
        self.assertEqual(timezone.localtime(demande.date_prevue).hour, 15)

        self.client.post(f"/infirmiers/interventions/{demande.pk}/liberer/")
        demande.refresh_from_db()
        self.assertEqual((demande.statut, demande.infirmier), (Statut.DEMANDEE, None))

        self.accepter(demande, f.demain(10))
        self.assertEqual(self.client.get(f"/infirmiers/interventions/{demande.pk}/annuler/").status_code, 200)
        self.assertRedirects(self.client.post(f"/infirmiers/interventions/{demande.pk}/annuler/", {"motif": "Patient hospitalisé."}),
                             "/infirmiers/planning/")
        demande.refresh_from_db()
        self.assertEqual((demande.statut, demande.motif_annulation), (Statut.ANNULEE, "Patient hospitalisé."))
        self.assertEqual(len(mail.outbox), 5)  # accepté, déplacé, désistement, accepté, annulé : le patient suit tout

    def test_tournee_regroupee_par_ville(self):
        jour = f.demain().date()
        a = demande_de(self.patient, ville="Ariana")
        b = demande_de(f.un_patient(), ville="Tunis")
        c = demande_de(f.un_patient(), ville="Ariana")
        for demande, heure in ((a, 9), (b, 10), (c, 11)):
            self.accepter(demande, f.demain(heure))
        page = self.client.get(f"/infirmiers/planning/{jour.isoformat()}/tournee/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["gain_villes"], 1)  # Ariana -> Tunis -> Ariana devient Tunis -> Ariana
        mail.outbox = []
        self.assertRedirects(self.client.post(f"/infirmiers/planning/{jour.isoformat()}/tournee/"), "/infirmiers/planning/")
        b.refresh_from_db()
        self.assertEqual(timezone.localtime(b.date_prevue).hour, 9)  # sa ville d'abord
        self.assertTrue(mail.outbox)

    def test_analyser_une_note_pre_remplit_les_constantes(self):
        demande = demande_de(self.patient)
        self.accepter(demande, f.demain(9))
        reponse = self.client.post(f"/infirmiers/interventions/{demande.pk}/compte-rendu/",
                                   {"action": "analyser", "compte_rendu": "Pansement fait. T 38,6 et pouls 104."})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(str(reponse.context["form"].initial["temperature"]), "38.6")
        self.assertEqual(reponse.context["analyse"].niveau, NiveauAlerte.SURVEILLER)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, Statut.ACCEPTEE)  # « Analyser » n'enregistre rien

    def test_historique_et_tableau_de_bord(self):
        self.assertEqual(self.client.get("/infirmiers/historique/").status_code, 200)
        self.assertEqual(self.client.get("/infirmiers/tableau-de-bord/").status_code, 200)
        self.assertEqual(self.client.get("/infirmiers/planning/2000-01-01/tournee/").status_code, 302)
        self.assertEqual(self.client.get("/infirmiers/planning/pas-une-date/tournee/").status_code, 404)
