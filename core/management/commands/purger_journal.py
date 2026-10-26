import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import JournalConnexion


class Command(BaseCommand):
    help = "Supprime les entrées du journal des connexions plus anciennes que --jours (90 par défaut) : l'adresse IP est une donnée personnelle."

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=90)

    def handle(self, *args, jours, **options):
        limite = timezone.now() - datetime.timedelta(days=jours)
        n = 0
        for entree in JournalConnexion.objects.filter(quand__lt=limite).only("pk"):
            entree.delete()
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} entrée(s) de plus de {jours} jours supprimée(s)."))
