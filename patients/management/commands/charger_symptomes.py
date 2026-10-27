from django.core.management.base import BaseCommand

from patients.models import Symptome

# (nom, poids, drapeau_rouge, niveau_minimal) — valeurs de démonstration.
SYMPTOMES = [
    # Signes d'alerte
    ("Douleur thoracique", 10, True, 1),
    ("Difficulté à respirer", 10, True, 1),
    ("Perte de connaissance", 10, True, 1),
    ("Saignement abondant", 10, True, 1),
    ("Paralysie ou trouble de la parole", 10, True, 1),
    ("Convulsions", 9, True, 2),
    ("Douleur abdominale intense", 8, True, 2),
    # Symptômes courants
    ("Toux", 2, False, None),
    ("Mal de gorge", 2, False, None),
    ("Maux de tête", 3, False, None),
    ("Vomissements", 4, False, None),
    ("Diarrhée", 3, False, None),
    ("Douleur abdominale", 4, False, None),
    ("Vertiges", 4, False, None),
    ("Éruption cutanée", 2, False, None),
    ("Fatigue", 1, False, None),
    ("Douleur musculaire ou articulaire", 2, False, None),
]

# Symptômes remplacés par une échelle d'auto-évaluation (voir echelles.py) :
# on les désactive pour ne pas compter deux fois la même chose.
REMPLACES_PAR_UNE_ECHELLE = ["Fièvre"]


class Command(BaseCommand):
    help = "Charge (ou met à jour) le catalogue de symptômes de départ."

    def handle(self, *args, **options):
        crees = 0
        for nom, poids, rouge, minimal in SYMPTOMES:
            _, cree = Symptome.objects.update_or_create(
                nom=nom,
                defaults={
                    "poids": poids,
                    "drapeau_rouge": rouge,
                    "niveau_minimal": minimal,
                    "actif": True,
                },
            )
            crees += cree
        desactives = Symptome.objects.filter(
            nom__in=REMPLACES_PAR_UNE_ECHELLE, actif=True
        ).update(actif=False)
        if desactives:
            self.stdout.write(f"{desactives} symptôme(s) remplacé(s) par une échelle : désactivé(s).")
        self.stdout.write(
            self.style.SUCCESS(f"{crees} symptôme(s) créé(s), {len(SYMPTOMES) - crees} mis à jour.")
        )
