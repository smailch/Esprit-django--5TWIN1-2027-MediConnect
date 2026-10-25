from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.test.utils import setup_test_environment

from core.accessibilite import SEUIL_TEXTE_NORMAL, contrastes_du_projet, verifier_html

PAGES_PUBLIQUES = ("/", "/comptes/connexion/", "/patients/inscription/", "/comptes/mot-de-passe-oublie/")
PAGES_PATIENT = (
    "/patients/tableau-de-bord/", "/patients/medecins/", "/patients/dossier/", "/patients/dossier/analyse/", "/patients/dossier/consultations/",
    "/patients/allergies/", "/patients/mesures/", "/patients/profil/", "/patients/compte/", "/comptes/mot-de-passe/",
)
PAGES_ADMIN = (
    "/backoffice/", "/backoffice/rendez-vous/", "/backoffice/file-attente/", "/backoffice/patients/", "/backoffice/parametres/", "/backoffice/modele-texte/",
)


class Command(BaseCommand):
    help = "Audit rapide d'accessibilité : contrastes (WCAG AA) et structure HTML des pages (titres, repères, étiquettes, icônes…)."

    def add_arguments(self, parser):
        parser.add_argument("--patient", help="identifiant d'un compte patient : audite aussi les pages de l'espace patient")
        parser.add_argument("--admin", help="identifiant d'un compte administrateur : audite aussi le back-office")

    def handle(self, *args, **options):
        try:
            setup_test_environment()  # le client de test a besoin de ses outils (ALLOWED_HOSTS = testserver)
        except RuntimeError:
            pass  # déjà en place (par exemple quand la commande est lancée depuis les tests)
        self.stdout.write(self.style.MIGRATE_HEADING("Contrastes (seuil WCAG AA : %s pour le texte normal)" % SEUIL_TEXTE_NORMAL))
        insuffisants = 0
        for nom, fg, bg, rapport in contrastes_du_projet():
            bon = rapport >= SEUIL_TEXTE_NORMAL
            insuffisants += not bon
            self.stdout.write(f"  {'OK  ' if bon else 'FAIL'} {rapport:5.2f}  {nom}  ({fg} sur {bg})")
        lots = [(Client(), PAGES_PUBLIQUES)]
        User = get_user_model()
        for option, pages in (("patient", PAGES_PATIENT), ("admin", PAGES_ADMIN)):
            if options[option]:
                try:
                    utilisateur = User.objects.get(username=options[option])
                except User.DoesNotExist:
                    raise CommandError(f"Compte introuvable : {options[option]}")
                client = Client()
                client.force_login(utilisateur)
                lots.append((client, pages))
        self.stdout.write(self.style.MIGRATE_HEADING("\nStructure des pages"))
        pages_en_defaut = 0
        for client, pages in lots:
            for url in pages:
                reponse = client.get(url)
                problemes = [f"statut HTTP {reponse.status_code}"] if reponse.status_code != 200 else verifier_html(reponse.content.decode("utf-8"))
                pages_en_defaut += bool(problemes)
                self.stdout.write(f"  {'OK  ' if not problemes else '!!  '} {url}")
                for p in problemes:
                    self.stdout.write(f"         - {p}")
        total = sum(len(pages) for _, pages in lots)
        resume = f"\n{total} pages vérifiées, {pages_en_defaut} avec un défaut ; {insuffisants} contraste(s) insuffisant(s)."
        self.stdout.write(self.style.SUCCESS(resume) if not (pages_en_defaut or insuffisants) else self.style.WARNING(resume))
