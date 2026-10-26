from django.core.management.base import BaseCommand

from core import roles


class Command(BaseCommand):
    help = "Crée les groupes Django des rôles, leur donne leurs permissions et range chaque compte dans le groupe de son rôle."

    def handle(self, *args, **options):
        for nom, nombre in roles.synchroniser_groupes().items():
            self.stdout.write(f"  {nom} : {nombre} permission(s)")
        self.stdout.write(self.style.SUCCESS(f"{roles.ranger_tous()} compte(s) rangé(s) dans le groupe de leur rôle."))
