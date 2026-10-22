from django.core.management.base import BaseCommand

from patients import ia_client, ia_taches
from patients.models import Symptome


class Command(BaseCommand):
    help = (
        "Vérifie la configuration de l'IA et la connexion au service (la clé n'est jamais affichée). "
        "Avec --phrase, essaie la détection de symptômes sur un texte."
    )

    def add_arguments(self, parser):
        parser.add_argument("--phrase", help="Texte libre à analyser, par exemple « Ça me serre la poitrine et je tousse ».")

    def handle(self, *args, **options):
        d = ia_client.description()
        self.stdout.write(f"Fournisseur : {d['nom']}")
        if not d["active"]:
            self.stdout.write(self.style.WARNING(ia_client.MESSAGES[ia_client.NON_CONFIGUREE]))
            if d["cle_requise"] and not d["cle_presente"]:
                self.stdout.write("Il manque la clé : ajoutez GROQ_API_KEY=… dans le fichier .env (voir .env.example).")
            return
        self.stdout.write(f"Modèle      : {d['modele']}")
        self.stdout.write(f"Service     : {d['hote']}")
        self.stdout.write(f"Clé d'API   : {'présente' if d['cle_presente'] else 'non requise'}")
        resultat = ia_client.tester_connexion()
        if not resultat.ok:
            self.stdout.write(self.style.ERROR(f"Échec : {resultat.message}"))
            return
        self.stdout.write(self.style.SUCCESS(f"Connexion réussie en {resultat.duree_ms} ms."))
        phrase = options.get("phrase")
        if not phrase:
            return
        noms = list(Symptome.objects.filter(actif=True).values_list("nom", flat=True))
        sortie = ia_taches.detecter_symptomes(phrase, noms)
        if not sortie.ok:
            self.stdout.write(self.style.ERROR(f"Analyse impossible : {ia_client.MESSAGES.get(sortie.statut, sortie.statut)}"))
            return
        detectes = sortie.elements["symptomes"]
        if not detectes:
            self.stdout.write("Aucun symptôme du catalogue repéré dans ce texte.")
        for nom, extrait in detectes:
            self.stdout.write(f"  - {nom} (« {extrait} »)")
        self.stdout.write(f"Analyse faite en {sortie.duree_ms} ms.")
