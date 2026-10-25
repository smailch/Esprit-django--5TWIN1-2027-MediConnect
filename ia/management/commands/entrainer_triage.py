from django.core.management.base import BaseCommand

from ia import modele


def _pourcent(valeur):
    return "—" if valeur is None else f"{valeur * 100:.1f} %"


class Command(BaseCommand):
    help = "Génère le jeu de données, entraîne le modèle de lecture du texte du triage, l'évalue et l'enregistre."

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=modele.TAILLE_ENTRAINEMENT, help="nombre de phrases d'entraînement")
        parser.add_argument("--graine", type=int, default=1, help="graine du générateur (mêmes phrases pour une même graine)")

    def handle(self, *args, **options):
        self.stdout.write(f"Génération de {options['n']} phrases d'entraînement (graine {options['graine']}) et entraînement…")
        entraine, evaluation = modele.entrainer(options["n"], options["graine"])
        modele.sauvegarder(entraine, evaluation)
        modele.installer(entraine)
        for titre, cle in (("Phrases générées (test)", "test_genere"), ("Phrases écrites à la main", "test_a_la_main")):
            e = evaluation[cle]
            self.stdout.write(self.style.SUCCESS(f"\n{titre} : {e['n']} phrases"))
            self.stdout.write(f"  niveau exact              : {_pourcent(e['precision'])}   (toujours répondre pareil : {_pourcent(e['reference_toujours_la_meme_reponse'])})")
            self.stdout.write(f"  à un niveau près          : {_pourcent(e['a_un_niveau_pres'])}")
            self.stdout.write(f"  cas graves repérés (1-2)  : {_pourcent(e['graves_reperes'])}   pris pour bénins : {_pourcent(e['graves_pris_pour_benins'])}")
            self.stdout.write(f"  fausses alertes (cas 4-5 vus comme 1-2) : {_pourcent(e['fausses_alertes'])}")
        self.stdout.write(self.style.SUCCESS(f"\nModèle enregistré dans {modele.DOSSIER_ARTEFACTS}"))
