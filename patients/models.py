from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django_mongodb_backend.fields import (
    ArrayField,
    EmbeddedModelArrayField,
    EmbeddedModelField,
)
from django_mongodb_backend.models import EmbeddedModel


class Patient(models.Model):
    class Sexe(models.TextChoices):
        FEMME = "F", "Femme"
        HOMME = "H", "Homme"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patient"
    )
    date_naissance = models.DateField()
    sexe = models.CharField(max_length=1, choices=Sexe.choices)
    telephone = models.CharField(max_length=20)
    adresse = models.CharField(max_length=255, blank=True)
    ville = models.CharField(
        max_length=100, help_text="Sert à trouver les infirmiers de la zone."
    )
    contact_urgence_nom = models.CharField(max_length=150, blank=True)
    contact_urgence_tel = models.CharField(max_length=20, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class DossierMedical(models.Model):
    class GroupeSanguin(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    patient = models.OneToOneField(
        Patient, on_delete=models.CASCADE, related_name="dossier"
    )
    groupe_sanguin = models.CharField(
        max_length=3, choices=GroupeSanguin.choices, blank=True
    )
    allergies = ArrayField(models.CharField(max_length=100), blank=True, default=list)
    antecedents = models.TextField(blank=True)
    traitements_en_cours = models.TextField(blank=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dossier médical"
        verbose_name_plural = "dossiers médicaux"

    def __str__(self):
        return f"Dossier de {self.patient}"


class Symptome(models.Model):
    """Catalogue des symptômes, géré par l'administrateur."""

    nom = models.CharField(max_length=100, unique=True)
    poids = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Gravité de 1 (léger) à 10 (très grave).",
    )
    drapeau_rouge = models.BooleanField(
        default=False,
        help_text="Impose un niveau d'urgence minimal, quel que soit le score.",
    )
    niveau_minimal = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Niveau d'urgence imposé si le symptôme est un drapeau rouge.",
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class SymptomeDeclare(EmbeddedModel):
    """Copie d'un symptôme au moment du triage (l'historique reste stable
    même si l'admin modifie ensuite le catalogue)."""

    nom = models.CharField(max_length=100)
    poids = models.PositiveSmallIntegerField()
    drapeau_rouge = models.BooleanField(default=False)


class ConstantesVitales(EmbeddedModel):
    temperature = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, help_text="°C"
    )
    tension_systolique = models.PositiveSmallIntegerField(null=True, blank=True)
    tension_diastolique = models.PositiveSmallIntegerField(null=True, blank=True)
    frequence_cardiaque = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="battements/min"
    )
    saturation_oxygene = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="SpO2 en %"
    )


class Triage(models.Model):
    class Niveau(models.IntegerChoices):
        VITAL = 1, "1 – Vital"
        TRES_URGENT = 2, "2 – Très urgent"
        URGENT = 3, "3 – Urgent"
        STANDARD = 4, "4 – Standard"
        NON_URGENT = 5, "5 – Non urgent"

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        EN_CONSULTATION = "en_consultation", "En consultation"
        TERMINE = "termine", "Terminé"
        ANNULE = "annule", "Annulé"

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="triages"
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    statut = models.CharField(
        max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE
    )

    # Médecin choisi par le patient. Provisoire : valeurs issues de
    # patients/medecins_test.py, à remplacer par une clé étrangère vers le
    # modèle Medecin quand le module `medecins` existera.
    medecin_id = models.CharField(max_length=50)
    medecin_nom = models.CharField(max_length=150)
    medecin_specialite = models.CharField(max_length=100, blank=True)

    # Ce que déclare le patient
    symptomes = EmbeddedModelArrayField(SymptomeDeclare, blank=True, default=list)
    constantes = EmbeddedModelField(ConstantesVitales, null=True, blank=True)
    texte_libre = models.TextField(blank=True)

    # Résultat du triage IA
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    niveau = models.PositiveSmallIntegerField(
        choices=Niveau.choices, null=True, blank=True
    )
    explication = models.TextField(blank=True)
    drapeaux_rouges = ArrayField(
        models.CharField(max_length=100), blank=True, default=list
    )

    # Le médecin garde la décision finale
    niveau_medecin = models.PositiveSmallIntegerField(
        choices=Niveau.choices,
        null=True,
        blank=True,
        help_text="Niveau requalifié par le médecin.",
    )

    class Meta:
        ordering = ["niveau", "cree_le"]
        indexes = [models.Index(fields=["medecin_id", "statut"])]

    @property
    def niveau_effectif(self):
        """Le niveau du médecin prime sur celui de l'IA."""
        return self.niveau_medecin or self.niveau

    @property
    def est_actif(self):
        return self.statut in (self.Statut.EN_ATTENTE, self.Statut.EN_CONSULTATION)

    @staticmethod
    def file_du_medecin(medecin_id):
        """Demandes en attente d'un médecin, dans l'ordre où il les verra :
        niveau le plus urgent d'abord, puis heure d'arrivée."""
        return sorted(
            Triage.objects.filter(medecin_id=medecin_id, statut=Triage.Statut.EN_ATTENTE),
            key=lambda t: (t.niveau_effectif or 5, t.cree_le),
        )

    def place_dans_la_file(self, file=None):
        """(position, total) dans la file du médecin, ou None si la demande
        n'est plus en attente. `file` permet de réutiliser une file déjà chargée."""
        if self.statut != self.Statut.EN_ATTENTE:
            return None
        file = file if file is not None else self.file_du_medecin(self.medecin_id)
        for position, t in enumerate(file, start=1):
            if t.pk == self.pk:
                return position, len(file)
        return None

    def __str__(self):
        return f"Triage {self.patient} – niveau {self.niveau_effectif or '?'}"
