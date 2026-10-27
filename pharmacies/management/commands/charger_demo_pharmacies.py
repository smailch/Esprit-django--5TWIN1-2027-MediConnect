import datetime
import os
import secrets
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from patients.models import Allergie, AutoEvaluation, Consultation, DossierMedical, Patient, Triage
from pharmacies.models import Medicament, Ordonnance, Pharmacie

# Préfixe distinct de celui de patients/charger_demo (« demo_ ») : les deux commandes ne se suppriment pas l'une l'autre.
PREFIXE = "demorx_"

PRESCRIPTION = "Amoxicilline 1 g, 1 comprimé matin et soir, 7 jours\nParacétamol 1 g, 1 comprimé toutes les 6 heures si fièvre, 5 jours"

# (statut, pharmacie ?, il y a (jours), médicaments)
ORDONNANCES = [
    (Ordonnance.Statut.EMISE, False, 1, PRESCRIPTION),
    (Ordonnance.Statut.EN_PREPARATION, True, 3, "Ventoline 100 µg, 2 bouffées en cas de gêne respiratoire\nSérum physiologique, lavage de nez matin et soir, 10 jours"),
    (Ordonnance.Statut.DELIVREE, True, 30, "Ibuprofène 400 mg, 1 comprimé 3 fois par jour pendant les repas, 3 jours"),
]

# Stock de la pharmacie : (nom, principe actif, dosage, forme, quantité, seuil d'alerte, prix en DT).
# L'amoxicilline est en RUPTURE (quantité 0) : l'ordonnance émise la contient, la démo de la substitution part de là.
STOCK = [
    ("Amoxicilline", "amoxicilline", "1 g", "comprime", 0, 5, "6.480"),
    ("Clamoxyl", "amoxicilline", "1 g", "comprime", 4, 5, "8.950"),
    ("Hiconcil", "amoxicilline", "1 g", "gelule", 12, 5, "7.200"),
    ("Doliprane", "paracétamol", "1 g", "comprime", 40, 10, "2.900"),
    ("Efferalgan", "paracétamol", "1 g", "comprime", 3, 10, "3.400"),
    ("Ventoline", "salbutamol", "100 µg", "inhalateur", 8, 3, "9.700"),
    ("Sérum physiologique", "chlorure de sodium", "", "autre", 25, 10, "1.200"),
    ("Advil", "ibuprofène", "400 mg", "comprime", 15, 5, "4.600"),
    ("Mopral", "oméprazole", "20 mg", "gelule", 0, 4, "11.300"),
]

# Une seconde pharmacie qui a ce qui manque à la première : la délivrance partielle y oriente le patient.
SECONDE_PHARMACIE = {"nom": "Pharmacie Ennasr", "adresse": "45 avenue Hédi Nouira, Ennasr 2", "ville": "Tunis",
                     "telephone": "71 820 456", "horaires": "Tous les jours, 8 h – 22 h", "de_garde": False}
STOCK_SECONDE = [
    ("Amoxicilline", "amoxicilline", "1 g", "comprime", 20, 5, "6.480"),
    ("Inexium", "ésoméprazole", "20 mg", "gelule", 6, 3, "14.200"),
    ("Mopral", "oméprazole", "20 mg", "gelule", 9, 4, "11.300"),
    ("Doliprane", "paracétamol", "1 g", "comprime", 30, 10, "2.900"),
]
STOCKS = {"pharmacie": STOCK, "pharmacie2": STOCK_SECONDE}


class Command(BaseCommand):
    help = "Crée une pharmacie, un médecin, un patient, une consultation et 3 ordonnances de démonstration (--supprimer pour les retirer)."

    def add_arguments(self, parser):
        parser.add_argument("--supprimer", action="store_true", help="Supprime les données de démonstration du module pharmacies.")
        parser.add_argument(
            "--mot-de-passe", dest="mot_de_passe",
            help="Mot de passe des comptes de démonstration (sinon DEMO_MOT_DE_PASSE, sinon un mot de passe aléatoire affiché).",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        if options["supprimer"]:
            return self.supprimer(User)
        # Aucun mot de passe écrit dans le code : il vient de l'option, de l'environnement, ou il est tiré au hasard.
        mot_de_passe = options["mot_de_passe"] or os.environ.get("DEMO_MOT_DE_PASSE") or secrets.token_urlsafe(9)
        aleatoire = not (options["mot_de_passe"] or os.environ.get("DEMO_MOT_DE_PASSE"))

        if User.objects.filter(username__startswith=PREFIXE).exists():
            seconde = self.ajouter_seconde_pharmacie(User, mot_de_passe)
            ajoutes = self.ajouter_stock()
            self.stdout.write(
                "Les données de démonstration sont déjà chargées (utilisez --supprimer pour les retirer)."
                + (f" {ajoutes} médicament(s) ajouté(s) au stock." if ajoutes else "")
            )
            if seconde:
                self.stdout.write(f"Seconde pharmacie créée : compte {PREFIXE}pharmacie2"
                                  + (f", mot de passe (tiré au hasard, à noter) : {mot_de_passe}" if aleatoire else ""))
            return

        def compte(identifiant, prenom, nom, role):
            user = User(username=PREFIXE + identifiant, first_name=prenom, last_name=nom, role=role, est_valide=True,
                        email=f"{identifiant}@demo.mediconnect.test")
            user.set_password(mot_de_passe)
            user.save()
            return user

        pharmacie = Pharmacie.objects.create(
            user=compte("pharmacie", "Hela", "Ben Salah", User.Role.PHARMACIE),
            nom="Pharmacie du Lac", adresse="12 rue du Lac Léman, Les Berges du Lac", ville="Tunis",
            telephone="71 960 123", horaires="Du lundi au samedi, 8 h – 20 h", de_garde=True,
        )
        compte("medecin", "Sara", "Benali", User.Role.MEDECIN)
        patient = Patient.objects.create(
            user=compte("patient", "Yassine", "Khelifi", User.Role.PATIENT),
            date_naissance=datetime.date(1992, 3, 14), sexe=Patient.Sexe.HOMME, telephone="22 456 789", ville="Tunis",
        )
        DossierMedical.objects.create(patient=patient)
        Allergie.objects.create(patient=patient, substance="Pénicilline", type=Allergie.Type.MEDICAMENT,
                                gravite=Allergie.Gravite.SEVERE, reaction="Gonflement du visage")

        maintenant = timezone.now()
        triage = Triage.objects.create(
            patient=patient, medecin_id="m1", medecin_nom="Dr Sara Benali", medecin_specialite="Médecine générale",
            statut=Triage.Statut.TERMINE, niveau=4, texte_libre="Mal de gorge et fièvre depuis deux jours.",
            auto_evaluation=AutoEvaluation(douleur=2, fievre=2, respiration=0, etat_general=1),
        )
        consultation = Consultation.objects.create(
            patient=patient, triage=triage, medecin_nom="Dr Sara Benali", medecin_specialite="Médecine générale",
            date=maintenant - datetime.timedelta(days=1), motif="Mal de gorge, fièvre",
            resume="Gorge rouge, ganglions sensibles, 38,6 °C.", diagnostic="Angine bactérienne", prescription=PRESCRIPTION,
        )

        for statut, avec_pharmacie, jours, medicaments in ORDONNANCES:
            emise = timezone.localdate() - datetime.timedelta(days=jours)
            Ordonnance.objects.create(
                patient=patient, consultation=consultation if statut == Ordonnance.Statut.EMISE else None,
                pharmacie=pharmacie if avec_pharmacie else None, prescripteur_nom="Dr Sara Benali",
                medicaments=medicaments, statut=statut, date_emission=emise,
                delivree_le=maintenant - datetime.timedelta(days=jours - 1) if statut == Ordonnance.Statut.DELIVREE else None,
            )

        self.ajouter_seconde_pharmacie(User, mot_de_passe)
        ajoutes = self.ajouter_stock()
        self.stdout.write(self.style.SUCCESS(
            f"2 pharmacies, médecin, patient, consultation, 3 ordonnances et {ajoutes} médicaments en stock de démonstration créés."
        ))
        self.stdout.write(f"Comptes : {PREFIXE}pharmacie, {PREFIXE}pharmacie2, {PREFIXE}medecin, {PREFIXE}patient")
        if aleatoire:
            self.stdout.write(f"Mot de passe (tiré au hasard, à noter) : {mot_de_passe}")

    def ajouter_seconde_pharmacie(self, User, mot_de_passe):
        """La seconde pharmacie de la démo (une seule fois). Renvoie True si elle vient d'être créée."""
        if User.objects.filter(username=PREFIXE + "pharmacie2").exists():
            return False
        user = User(username=PREFIXE + "pharmacie2", first_name="Karim", last_name="Mansour", role=User.Role.PHARMACIE,
                    est_valide=True, email="pharmacie2@demo.mediconnect.test")
        user.set_password(mot_de_passe)
        user.save()
        Pharmacie.objects.create(user=user, **SECONDE_PHARMACIE)
        return True

    def ajouter_stock(self):
        """Stock de démonstration de chaque pharmacie (sans doublon si la commande est relancée)."""
        ajoutes = 0
        for compte, lignes in STOCKS.items():
            pharmacie = Pharmacie.objects.filter(user__username=PREFIXE + compte).first()
            if pharmacie is None:
                continue
            for nom, principe, dosage, forme, quantite, seuil, prix in lignes:
                if Medicament.objects.filter(pharmacie=pharmacie, nom=nom, dosage=dosage).exists():
                    continue
                Medicament.objects.create(pharmacie=pharmacie, nom=nom, principe_actif=principe, dosage=dosage, forme=forme,
                                          quantite=quantite, seuil_alerte=seuil, prix=Decimal(prix))
                ajoutes += 1
        return ajoutes

    def supprimer(self, User):
        # MongoDB ne supprime pas à travers plusieurs collections : objet par objet, des feuilles vers les comptes.
        comptes = 0
        for user in User.objects.filter(username__startswith=PREFIXE):
            for patient in Patient.objects.filter(user=user):
                for modele in (Ordonnance, Consultation, Triage, Allergie, DossierMedical):
                    for objet in modele.objects.filter(patient=patient):
                        objet.delete()
                patient.delete()
            for pharmacie in Pharmacie.objects.filter(user=user):
                for medicament in Medicament.objects.filter(pharmacie=pharmacie):
                    medicament.delete()
                pharmacie.delete()
            user.delete()
            comptes += 1
        self.stdout.write(self.style.SUCCESS(f"{comptes} compte(s) de démonstration supprimé(s)."))
