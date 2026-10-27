"""Données de démonstration des soins à domicile : trois infirmiers et des interventions à toutes les étapes.

S'appuie sur les patients de démonstration de l'app patients (lancez d'abord `charger_symptomes` puis `charger_demo`).
Les comptes rendus sont analysés par les règles seulement (aucun appel à l'IA) et leurs constantes rejoignent les
mesures de santé des patients, comme en vrai. `--supprimer` retire tout ce que la commande a créé.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from patients.models import ConstantesVitales, Mesure, Patient

from infirmiers import dossier, ia_soin
from infirmiers.models import Infirmier, InterventionDomicile, TypeSoin

PREFIXE = "demo_inf_"
PREFIXE_PATIENTS = "demo_"  # patients créés par patients/management/commands/charger_demo.py

# (identifiant, prénom, nom, téléphone, numéro d'Ordre, ville, autres villes, soins (vide : tous), validé)
INFIRMIERS = [
    ("sami", "Sami", "Ben Ali", "21100100", "TN-10231", "Tunis", ["Ariana", "La Marsa"], [], True),
    ("ines", "Inès", "Hamdi", "21100200", "TN-10544", "Sfax", [], [TypeSoin.PRELEVEMENT, TypeSoin.INJECTION, TypeSoin.SURVEILLANCE], True),
    ("karim", "Karim", "Mansour", "21100300", "TN-10872", "Sousse", [], [], False),  # en attente de validation
]

ADRESSES = {
    "amel": "12 rue de Marseille", "hichem": "5 avenue de Carthage", "rami": "8 rue d'Alger",
    "karim": "3 route de Gabès", "nour": "21 avenue Hédi Chaker", "sonia": "14 boulevard du 14 Janvier",
}

# Passages terminés : (patient, infirmier, soin, il y a combien d'heures, note de l'infirmier).
# Ordre chronologique : chaque compte rendu est comparé aux relevés précédents (tension de Hichem en hausse).
REALISEES = [
    ("hichem", "sami", TypeSoin.PANSEMENT, 120, "Pansement de l'ulcère de la jambe gauche refait, plaie propre. T 36,9, TA 15/9, pouls 76."),
    ("amel", "sami", TypeSoin.INJECTION, 96, "Injection d'anticoagulant faite, bonne tolérance. Pas de rougeur. T 36,8, TA 12/7, pouls 70."),
    ("karim", "ines", TypeSoin.PRELEVEMENT, 76, "Prélèvement fait à jeun. Patient essoufflé en montant l'escalier, sat 93 %. Pouls 104."),
    ("hichem", "sami", TypeSoin.PANSEMENT, 72, "Pansement refait. Légère douleur au retrait. T 37,1, TA 154/92, pouls 80."),
    ("hichem", "sami", TypeSoin.PANSEMENT, 1, "Pansement refait. Plaie un peu rouge et chaude sur le bord, le patient dit avoir eu des frissons cette nuit. T 38,2, TA 160/98, pouls 92."),
]

# Passages acceptés : (patient, infirmier, soin, dans combien d'heures (négatif : dépassé, compte rendu à saisir), détail)
ACCEPTEES = [
    ("amel", "sami", TypeSoin.INJECTION, 2, "Injection d'anticoagulant, une fois par jour."),
    ("rami", "sami", TypeSoin.SURVEILLANCE, -3, "Contrôle de la tension après changement de traitement."),
    ("hichem", "sami", TypeSoin.PANSEMENT, 26, "Pansement de l'ulcère de la jambe gauche."),
]

# Demandes en attente : (patient, soin, dans combien de jours, moment, détail)
DEMANDEES = [
    ("rami", TypeSoin.PRELEVEMENT, 1, "matin", "Prise de sang à jeun : bilan lipidique."),
    ("nour", TypeSoin.PRELEVEMENT, 1, "matin", "Prise de sang : numération et ferritine."),
    ("karim", TypeSoin.INJECTION, 2, "apres_midi", "Vaccin antigrippal, ordonnance disponible."),
    ("sonia", TypeSoin.INJECTION, 1, "indifferent", "Injection de vitamine B12."),  # Sousse : aucun infirmier validé
]

ANNULEES = [("amel", TypeSoin.PANSEMENT, "Patiente hospitalisée, soin plus nécessaire.")]


class Command(BaseCommand):
    help = "Charge des infirmiers et des soins à domicile fictifs pour la démonstration (--supprimer pour les retirer)."

    def add_arguments(self, parser):
        parser.add_argument("--supprimer", action="store_true", help="Supprime les données de démonstration des soins à domicile.")
        parser.add_argument(
            "--mot-de-passe", dest="mot_de_passe",
            help="Mot de passe des comptes infirmiers de démonstration (sans lui, ils ne peuvent pas se connecter).",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        if options["supprimer"]:
            return self.supprimer(User)
        if User.objects.filter(username__startswith=PREFIXE).exists():
            self.stdout.write("Les données de démonstration des soins à domicile sont déjà chargées (utilisez --supprimer pour les retirer).")
            return
        patients = {
            p.user.username[len(PREFIXE_PATIENTS):]: p
            for p in Patient.objects.select_related("user").filter(user__username__startswith=PREFIXE_PATIENTS)
        }
        manquants = set(ADRESSES) - set(patients)
        if manquants:
            self.stdout.write(self.style.ERROR("Patients de démonstration introuvables : lancez d'abord charger_symptomes puis charger_demo."))
            return

        self.maintenant = timezone.now().replace(second=0, microsecond=0)
        infirmiers = self.creer_infirmiers(User, options["mot_de_passe"])
        realisees = sum(self.realiser(patients[p], infirmiers[i], soin, heures, note) for p, i, soin, heures, note in REALISEES)
        for p, i, soin, heures, detail in ACCEPTEES:
            self.accepter(patients[p], infirmiers[i], soin, heures, detail)
        for p, soin, jours, moment, detail in DEMANDEES:
            self.demander(patients[p], soin, jours, moment, detail)
        for p, soin, motif in ANNULEES:
            self.annuler(patients[p], soin, motif)

        self.stdout.write(self.style.SUCCESS(
            f"{len(INFIRMIERS)} infirmiers et {len(REALISEES) + len(ACCEPTEES) + len(DEMANDEES) + len(ANNULEES)} interventions "
            f"de démonstration créés ; {realisees} mesure(s) ajoutée(s) aux dossiers des patients."
        ))
        if options["mot_de_passe"]:
            self.stdout.write(f"Connexion : {PREFIXE}sami (Tunis), {PREFIXE}ines (Sfax), {PREFIXE}karim (Sousse, non validé).")
        else:
            self.stdout.write("Les comptes infirmiers n'ont pas de mot de passe : relancez avec --supprimer puis --mot-de-passe pour vous y connecter.")

    # --- création ----------------------------------------------------------------------------------------

    def creer_infirmiers(self, User, mot_de_passe):
        infirmiers = {}
        for ident, prenom, nom, telephone, numero, ville, zones, soins, valide in INFIRMIERS:
            user = User(
                username=PREFIXE + ident, first_name=prenom, last_name=nom, email=f"{ident}.infirmier@demo.mediconnect.test",
                role=User.Role.INFIRMIER, est_valide=valide,
            )
            if mot_de_passe:
                user.set_password(mot_de_passe)
            else:
                user.set_unusable_password()
            user.save()
            infirmiers[ident] = Infirmier.objects.create(
                user=user, telephone=telephone, numero_ordre=numero, ville=ville, zones=zones, soins=soins
            )
        return infirmiers

    def _nouvelle(self, patient, soin, **champs):
        ident = patient.user.username[len(PREFIXE_PATIENTS):]
        return InterventionDomicile(
            patient=patient, type_soin=soin, adresse=ADRESSES[ident], ville=patient.ville, **champs
        )

    def _dater(self, intervention, cree_le):
        """La date de création est posée automatiquement : on la recule pour que l'histoire soit cohérente."""
        InterventionDomicile.objects.filter(pk=intervention.pk).update(cree_le=cree_le)

    def realiser(self, patient, infirmier, soin, heures, note):
        """Passage terminé il y a `heures` heures : compte rendu analysé par les règles, mesures ajoutées au dossier."""
        quand = self.maintenant - datetime.timedelta(hours=heures)
        intervention = self._nouvelle(
            patient, soin, date_souhaitee=timezone.localdate(quand), statut=InterventionDomicile.Statut.ACCEPTEE,
            infirmier=infirmier, date_prevue=quand, acceptee_le=quand - datetime.timedelta(days=1),
        )
        intervention.save()
        analyse = ia_soin.analyser(
            note, historique=dossier.historique(intervention),
            noms_patient=(patient.user.first_name, patient.user.last_name), utiliser_ia=False,
        )
        valeurs = {nom: v for nom, (v, _, _) in analyse.constantes.items()}
        if "temperature" in valeurs:
            valeurs["temperature"] = Decimal(str(valeurs["temperature"]))
        for nom in ("tension_systolique", "tension_diastolique", "frequence_cardiaque", "saturation_oxygene"):
            if nom in valeurs:
                valeurs[nom] = int(valeurs[nom])
        intervention.terminer(note, ConstantesVitales(**valeurs) if valeurs else None, realisee_le=quand, analyse=analyse)
        intervention.save()
        self._dater(intervention, quand - datetime.timedelta(days=2))
        return dossier.enregistrer_mesures(intervention)

    def accepter(self, patient, infirmier, soin, heures, detail):
        quand = (self.maintenant + datetime.timedelta(hours=heures)).replace(minute=0 if heures < 0 else 30)
        intervention = self._nouvelle(
            patient, soin, description=detail, date_souhaitee=timezone.localdate(quand),
            statut=InterventionDomicile.Statut.ACCEPTEE, infirmier=infirmier, date_prevue=quand,
            acceptee_le=self.maintenant - datetime.timedelta(hours=20),
        )
        intervention.save()
        self._dater(intervention, self.maintenant - datetime.timedelta(days=1))

    def demander(self, patient, soin, jours, moment, detail):
        intervention = self._nouvelle(
            patient, soin, description=detail, moment=moment,
            date_souhaitee=timezone.localdate() + datetime.timedelta(days=jours),
        )
        intervention.full_clean()
        intervention.save()
        self._dater(intervention, self.maintenant - datetime.timedelta(hours=5))

    def annuler(self, patient, soin, motif):
        intervention = self._nouvelle(patient, soin, date_souhaitee=timezone.localdate() + datetime.timedelta(days=1))
        intervention.full_clean()
        intervention.save()
        intervention.annuler(motif)
        intervention.save()

    # --- suppression ---------------------------------------------------------------------------------------

    def supprimer(self, User):
        # MongoDB ne supprime pas à travers plusieurs collections : objet par objet.
        interventions = mesures = 0
        for patient in Patient.objects.filter(user__username__startswith=PREFIXE_PATIENTS):
            for intervention in InterventionDomicile.objects.filter(patient=patient):
                intervention.delete()
                interventions += 1
            for mesure in Mesure.objects.filter(patient=patient, note__startswith="Relevé par l'infirmier"):
                mesure.delete()
                mesures += 1
        comptes = 0
        for user in User.objects.filter(username__startswith=PREFIXE):
            user.delete()  # le profil infirmier part avec le compte
            comptes += 1
        self.stdout.write(self.style.SUCCESS(
            f"{comptes} infirmier(s), {interventions} intervention(s) et {mesures} mesure(s) de démonstration supprimés."
        ))
