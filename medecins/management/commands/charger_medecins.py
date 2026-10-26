from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from medecins.models import Medecin, PlageHoraire

MOT_DE_PASSE = "MediConnect-2027"
SEMAINE = {j: [(9, 12), (14, 17)] for j in range(5)}

# Jeu de démonstration, chargé une fois en base. L'application ne lit plus cette liste.
DEMONSTRATION = [
    {"id": "m1", "prenom": "Sara", "nom": "Benali", "specialite": "Médecine générale", "ville": "Tunis", "disponible": True, "horaires": SEMAINE},
    {"id": "m2", "prenom": "Karim", "nom": "Trabelsi", "specialite": "Cardiologie", "ville": "Tunis", "disponible": True,
     "horaires": {1: [(9, 13)], 3: [(9, 13)], 2: [(14, 18)]}},
    {"id": "m3", "prenom": "Leïla", "nom": "Mansouri", "specialite": "Pédiatrie", "ville": "Sfax", "disponible": False, "horaires": {}},
    {"id": "m4", "prenom": "Youssef", "nom": "Haddad", "specialite": "Médecine générale", "ville": "Sousse", "disponible": True,
     "horaires": {j: [(8, 12)] for j in range(6)}},
    {"id": "m5", "prenom": "Amina", "nom": "Gharbi", "specialite": "Pneumologie", "ville": "Sfax", "disponible": True,
     "horaires": {0: [(10, 12), (14, 16)], 2: [(10, 12), (14, 16)], 4: [(10, 12), (14, 16)]}},
    {"id": "m6", "prenom": "Walid", "nom": "Jelassi", "specialite": "Urgences", "ville": "Tunis", "disponible": True,
     "horaires": {j: [(8, 20)] for j in range(7)}},
]


class Command(BaseCommand):
    help = (
        "Crée les comptes médecins de démonstration (identifiants m1…m6, "
        f"mot de passe {MOT_DE_PASSE}). Les patients ne voient que ces profils une fois enregistrés."
    )

    def handle(self, *args, **options):
        User = get_user_model()
        for fiche in DEMONSTRATION:
            code = fiche["id"]
            utilisateur = User.objects.filter(username=code).first()
            if utilisateur is None:
                utilisateur = User.objects.create_user(
                    username=code,
                    password=MOT_DE_PASSE,
                    first_name=fiche["prenom"],
                    last_name=fiche["nom"],
                    email=f"{code}@demo.mediconnect.local",
                    role=User.Role.MEDECIN,
                    est_valide=True,
                )
                self.stdout.write(self.style.SUCCESS(f"Compte {code} créé."))
            else:
                utilisateur.first_name = fiche["prenom"]
                utilisateur.last_name = fiche["nom"]
                utilisateur.role = User.Role.MEDECIN
                utilisateur.est_valide = True
                utilisateur.save()

            medecin = Medecin.objects.filter(code=code).first()
            if medecin is None:
                medecin = Medecin(code=code, user=utilisateur)
            elif medecin.user_id != utilisateur.pk:
                self.stdout.write(self.style.WARNING(f"{code} est déjà lié à un autre compte : ignoré."))
                continue
            medecin.specialite = fiche["specialite"]
            medecin.ville = fiche["ville"]
            medecin.disponible = fiche["disponible"]
            medecin.plages = [
                PlageHoraire(jour=int(jour), debut=int(debut), fin=int(fin))
                for jour, creneaux in fiche.get("horaires", {}).items()
                for debut, fin in creneaux
            ]
            medecin.save()
            self.stdout.write(f"Dr {fiche['prenom']} {fiche['nom']} ({code}) est prêt.")
        self.stdout.write(f"Connexion : identifiant m1 (ou m2…), mot de passe {MOT_DE_PASSE}.")
