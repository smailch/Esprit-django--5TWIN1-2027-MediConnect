from django.conf import settings
from django.db import models
from django_mongodb_backend.fields import EmbeddedModelArrayField
from django_mongodb_backend.models import EmbeddedModel


class PlageHoraire(EmbeddedModel):
    """Une plage de présence, en heures pleines. Lundi = 0, comme dans la file d'attente."""

    jour = models.PositiveSmallIntegerField()
    debut = models.PositiveSmallIntegerField()
    fin = models.PositiveSmallIntegerField()


class Medecin(models.Model):
    """Profil d'un médecin. `code` est l'identifiant stocké sur les demandes des patients."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="medecin"
    )
    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Identifiant stable repris par les demandes (ex. m1).",
    )
    specialite = models.CharField(max_length=100)
    ville = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20, blank=True)
    numero_ordre = models.CharField("Numéro d'ordre", max_length=50, blank=True)
    disponible = models.BooleanField(
        default=True,
        help_text="Décochez pour fermer la prise de rendez-vous (congés, absence).",
    )
    presentation = models.TextField(blank=True)
    plages = EmbeddedModelArrayField(PlageHoraire, blank=True, default=list)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name"]
        verbose_name = "médecin"
        verbose_name_plural = "médecins"

    def __str__(self):
        return self.nom_affiche

    @property
    def nom_affiche(self):
        nom = self.user.get_full_name()
        return f"Dr {nom}" if nom else self.user.get_username()

    def vers_fiche(self):
        """Fiche lue par le parcours patient : id, nom, spécialité, ville, disponibilité, horaires."""
        return {
            "id": self.code,
            "nom": self.nom_affiche,
            "specialite": self.specialite,
            "ville": self.ville,
            "disponible": self.disponible,
            "horaires": self.horaires_planning(),
        }

    def horaires_planning(self):
        """Dict {jour: [(début, fin), ...]} attendu par la file d'attente. Vide si le médecin est absent."""
        if not self.disponible:
            return {}
        resultat = {}
        for plage in self.plages or []:
            resultat.setdefault(int(plage.jour), []).append((int(plage.debut), int(plage.fin)))
        for jour in resultat:
            resultat[jour].sort()
        return resultat


class Prescription(models.Model):
    """Acte prescrit à la fin d'une consultation : ordonnance, examen ou soin à domicile.

    Les apps pharmacie, laboratoire et infirmier s'y brancheront. Le texte est aussi recopié
    dans le compte rendu, pour que le patient le voie dans son dossier.
    """

    class Type(models.TextChoices):
        ORDONNANCE = "ordonnance", "Ordonnance"
        EXAMEN = "examen", "Examen de laboratoire"
        SOIN = "soin", "Soin à domicile"

    consultation = models.ForeignKey(
        "patients.Consultation", on_delete=models.CASCADE, related_name="actes"
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    contenu = models.TextField()
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["type", "cree_le"]
        verbose_name = "prescription"
        verbose_name_plural = "prescriptions"

    def __str__(self):
        return f"{self.get_type_display()} – {self.consultation}"
