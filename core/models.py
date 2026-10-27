from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        PATIENT = "patient", "Patient"
        MEDECIN = "medecin", "Médecin"
        INFIRMIER = "infirmier", "Infirmier"
        PHARMACIE = "pharmacie", "Pharmacie"
        LABORATOIRE = "laboratoire", "Laboratoire"
        ADMIN = "admin", "Administrateur"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)
    est_valide = models.BooleanField(
        default=True,
        help_text="Les professionnels doivent être validés par un administrateur.",
    )

    @property
    def est_professionnel(self):
        """Médecin, infirmier, pharmacie ou laboratoire : compte soumis à la validation d'un administrateur."""
        return self.role in (self.Role.MEDECIN, self.Role.INFIRMIER, self.Role.PHARMACIE, self.Role.LABORATOIRE)


class JournalConnexion(models.Model):
    """Traçabilité des accès : connexions, échecs, blocages et déconnexions (voir core/securite.py).

    L'adresse IP est une donnée personnelle : les entrées de plus de 90 jours sont supprimées par
    « python manage.py purger_journal »."""

    class Evenement(models.TextChoices):
        CONNEXION = "connexion", "Connexion"
        ECHEC = "echec", "Échec de connexion"
        BLOCAGE = "blocage", "Connexion bloquée"
        DECONNEXION = "deconnexion", "Déconnexion"

    quand = models.DateTimeField(default=timezone.now, db_index=True)
    evenement = models.CharField(max_length=20, choices=Evenement.choices)
    utilisateur = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="journal_connexions")
    identifiant = models.CharField(max_length=150, blank=True, help_text="Identifiant saisi (même s'il n'existe pas).")
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    navigateur = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-quand"]
        verbose_name = "entrée du journal des connexions"
        verbose_name_plural = "journal des connexions"

    def __str__(self):
        return f"{self.get_evenement_display()} — {self.identifiant or '?'} — {self.quand:%d/%m/%Y %H:%M}"
