import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from infirmiers import evaluation, ia_soin
from patients import ia_client


class Command(BaseCommand):
    help = ("Mesure la détection des signes d'alerte sur le corpus annoté (infirmiers/evaluation/notes_annotees.json) : "
            "règles seules, puis règles + IA si elle est configurée. Écrit infirmiers/evaluation/resultats.json.")

    def add_arguments(self, parser):
        parser.add_argument("--sans-ia", action="store_true", help="n'évalue que les règles (aucun appel réseau)")
        parser.add_argument("--ne-pas-ecrire", action="store_true", help="affiche sans mettre à jour resultats.json")
        parser.add_argument("--pause", type=float, default=2.5, help="secondes entre deux appels à l'IA (limite de débit)")

    def handle(self, *args, sans_ia, ne_pas_ecrire, pause, **options):
        notes = evaluation.charger()
        self.stdout.write(f"Corpus : {len(notes)} notes annotées.\n")

        def analyser(texte, utiliser_ia):
            return ia_soin.analyser(texte, utiliser_ia=utiliser_ia)

        resultats = {"date": timezone.localtime().isoformat(timespec="minutes"), "corpus": len(notes)}
        resultats["regles"] = evaluation.evaluer(notes, analyser)
        self._afficher("Règles seules", resultats["regles"])

        if not sans_ia and ia_client.est_active():
            config = ia_client.configuration()
            resultats["ia"] = evaluation.evaluer(notes, analyser, avec_ia=True, pause=pause)
            resultats["ia"]["fournisseur"] = f"{config.fournisseur} ({config.modele})"
            self._afficher(f"Règles + IA — {resultats['ia']['fournisseur']}", resultats["ia"])
        elif not sans_ia:
            self.stdout.write(self.style.WARNING("IA non configurée (IA_FOURNISSEUR) : seules les règles sont évaluées."))

        if not ne_pas_ecrire:
            evaluation.RESULTATS.write_text(json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"\nRésultats écrits dans {evaluation.RESULTATS}"))

    def _afficher(self, titre, r):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{titre}"))
        self.stdout.write(f"  Exactitude {r['exactitude']:.0%} · F1 macro {r['f1_macro']:.2f} · "
                          f"alertes manquées {r['alertes_manquees']} · fausses alertes {r['fausses_alertes']}")
        self.stdout.write(f"  {'niveau':<12}{'précision':>10}{'rappel':>8}{'F1':>7}{'notes':>7}")
        for niveau, m in r["par_niveau"].items():
            self.stdout.write(f"  {niveau:<12}{m['precision']:>10.2f}{m['rappel']:>8.2f}{m['f1']:>7.2f}{m['support']:>7}")
        self.stdout.write("  Matrice (lignes = attendu, colonnes = prédit : ras, surveiller, signaler)")
        for niveau, ligne in zip(evaluation.NIVEAUX, r["matrice"]["valeurs"]):
            self.stdout.write(f"    {niveau:<12}" + "".join(f"{v:>6}" for v in ligne))
        if "temps_ms" in r:
            t = r["temps_ms"]
            self.stdout.write(f"  Temps par note : moyenne {t['moyenne']} ms, médiane {t['mediane']} ms, p95 {t['p95']} ms, max {t['max']} ms")
            self.stdout.write(f"  Statuts de l'IA : {r['statuts_ia']}")
