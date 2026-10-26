from django.core.management.base import BaseCommand

from ia import specialite


def _pourcent(valeur):
    return "—" if valeur is None else f"{valeur * 100:.1f} %"


class Command(BaseCommand):
    help = "Génère le jeu de données, entraîne le modèle d'orientation vers une spécialité, l'évalue et l'enregistre."

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=specialite.TAILLE_ENTRAINEMENT, help="nombre de phrases d'entraînement")
        parser.add_argument("--graine", type=int, default=1, help="graine du générateur (mêmes phrases pour une même graine)")

    def handle(self, *args, **options):
        self.stdout.write(f"Génération de {options['n']} phrases d'entraînement (graine {options['graine']}) et entraînement...")
        entraine, evaluation = specialite.entrainer(options["n"], options["graine"])
        specialite.sauvegarder(entraine, evaluation)
        specialite.installer(entraine)
        for titre, cle in (("Phrases générées (test)", "test_genere"), ("Phrases écrites à la main", "test_a_la_main")):
            e = evaluation[cle]
            self.stdout.write(self.style.SUCCESS(f"\n{titre} : {e['n']} phrases"))
            self.stdout.write(f"  bonne spécialité : {_pourcent(e['precision'])}   (toujours répondre pareil : {_pourcent(e['reference_toujours_la_meme_reponse'])})")
            self.stdout.write(f"  F1 moyen         : {_pourcent(e['f1_moyen'])}")
            for nom, f1 in e["f1_par_specialite"].items():
                self.stdout.write(f"    {nom:<20} F1 {_pourcent(f1)}")
        self.stdout.write(self.style.SUCCESS(f"\nModèle enregistré dans {specialite.DOSSIER_ARTEFACTS}"))
