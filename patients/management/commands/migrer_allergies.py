from django.core.management.base import BaseCommand

from patients.models import Allergie, DossierMedical


class Command(BaseCommand):
    help = (
        "Reprend les allergies saisies dans l'ancien champ texte du dossier médical "
        "et en fait de vraies allergies (relançable sans créer de doublons)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--simuler", action="store_true", help="Affiche ce qui serait fait, sans rien modifier.")

    def handle(self, *args, **options):
        simuler = options["simuler"]
        creees = deja = dossiers = 0
        for dossier in DossierMedical.objects.all():
            anciennes = [a.strip() for a in (dossier.allergies or []) if a and a.strip()]
            if not anciennes:
                continue
            dossiers += 1
            for nom in anciennes:
                nom = " ".join(nom.split())
                if Allergie.objects.filter(patient=dossier.patient, substance__iexact=nom).exists():
                    deja += 1
                    continue
                self.stdout.write(f"  {dossier.patient} : {nom}")
                if not simuler:
                    # La gravité et le type ne sont pas connus : valeurs prudentes, modifiables ensuite.
                    Allergie.objects.create(
                        patient=dossier.patient,
                        substance=nom,
                        type=Allergie.Type.AUTRE,
                        gravite=Allergie.Gravite.MODEREE,
                        reaction="",
                    )
                creees += 1
            if not simuler:
                # Les données sont désormais dans la table des allergies : on vide l'ancien champ
                # (le champ lui-même reste en base, rien n'est supprimé du schéma).
                dossier.allergies = []
                dossier.save(update_fields=["allergies"])
        etat = "à créer" if simuler else "créée(s)"
        self.stdout.write(self.style.SUCCESS(
            f"{creees} allergie(s) {etat}, {deja} déjà présente(s), {dossiers} dossier(s) concerné(s)."
        ))
