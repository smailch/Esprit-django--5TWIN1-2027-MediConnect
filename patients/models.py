from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django_mongodb_backend.fields import (
    ArrayField,
    EmbeddedModelArrayField,
    EmbeddedModelField,
)
from django_mongodb_backend.models import EmbeddedModel

from .echelles import ECHELLES, NIVEAU_MAX, NIVEAU_MIN


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


class Allergie(models.Model):
    """Une allergie d'un patient. Un patient peut en avoir plusieurs (relation ForeignKey)."""

    class Type(models.TextChoices):
        MEDICAMENT = "medicament", "Médicament"
        ALIMENT = "aliment", "Aliment"
        ENVIRONNEMENT = "environnement", "Environnement (pollen, acariens…)"
        AUTRE = "autre", "Autre"

    class Gravite(models.TextChoices):
        LEGERE = "legere", "Légère"
        MODEREE = "moderee", "Modérée"
        SEVERE = "severe", "Sévère"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    substance = models.CharField(
        max_length=100, help_text="Ce qui provoque l'allergie (ex. pénicilline, arachide, pollen)."
    )
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.AUTRE)
    gravite = models.CharField(max_length=10, choices=Gravite.choices, default=Gravite.MODEREE)
    reaction = models.CharField(
        max_length=200, blank=True, help_text="Ce que vous ressentez (ex. éruption, gonflement, gêne respiratoire)."
    )
    decouverte_le = models.DateField(null=True, blank=True, help_text="Date approximative de la première réaction.")
    active = models.BooleanField(default=True, help_text="Décochez si l'allergie a disparu.")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "allergie"
        verbose_name_plural = "allergies"
        ordering = ["substance"]

    def __str__(self):
        return f"{self.substance} ({self.get_gravite_display().lower()})"

    @property
    def est_severe(self):
        return self.gravite == self.Gravite.SEVERE

    def _doublon_existe(self):
        """Une autre allergie du même patient porte-t-elle la même substance (sans tenir compte des majuscules) ?"""
        autres = Allergie.objects.filter(patient=self.patient, substance__iexact=self.substance)
        if self.pk:
            autres = autres.exclude(pk=self.pk)
        return autres.exists()

    def clean(self):
        super().clean()
        erreurs = {}
        self.substance = " ".join((self.substance or "").split())  # espaces superflus retirés

        if self.substance and self.patient_id is not None and self._doublon_existe():
            erreurs["substance"] = "Cette allergie est déjà enregistrée pour ce patient."

        if self.decouverte_le:
            from django.utils import timezone

            if self.decouverte_le > timezone.localdate():
                erreurs["decouverte_le"] = "La date ne peut pas être dans le futur."
            else:
                naissance = getattr(self.patient, "date_naissance", None) if self.patient_id is not None else None
                if naissance and self.decouverte_le < naissance:
                    erreurs["decouverte_le"] = "La date ne peut pas être avant la naissance du patient."
        if erreurs:
            raise ValidationError(erreurs)


class Mesure(models.Model):
    """Une mesure de santé saisie par le patient (poids, tension, glycémie, température).

    Un patient peut avoir plusieurs mesures (relation ForeignKey). La tension est la
    pression systolique (le « grand chiffre » du tensiomètre).
    """

    class Type(models.TextChoices):
        POIDS = "poids", "Poids"
        TENSION = "tension", "Tension artérielle"
        GLYCEMIE = "glycemie", "Glycémie"
        TEMPERATURE = "temperature", "Température"
        FREQUENCE = "frequence", "Fréquence cardiaque"
        SATURATION = "saturation", "Saturation en oxygène"

    # type -> (unité, minimum plausible, maximum plausible, seuil bas, seuil haut) ; seuils : simples repères
    REGLES = {
        "poids": ("kg", 2, 400, None, None),
        "tension": ("mmHg", 50, 260, 90, 140),
        "glycemie": ("g/L", 0.2, 6, 0.7, 1.26),
        "temperature": ("°C", 30, 45, 35.5, 38),
        "frequence": ("bpm", 20, 250, 50, 101),  # au repos : « haute » à partir de 101
        "saturation": ("%", 50, 100, 94, None),
    }
    # Tension : le second chiffre (diastolique) a ses propres bornes (minimum, maximum, seuil bas, seuil haut).
    DIASTOLE = (30, 150, 60, 90)

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="mesures")
    type = models.CharField(max_length=15, choices=Type.choices)
    valeur = models.FloatField(help_text="Pour la tension : le premier chiffre (systolique, le plus grand).")
    valeur2 = models.FloatField(
        null=True, blank=True, help_text="Uniquement pour la tension : le second chiffre (diastolique)."
    )
    mesure_le = models.DateTimeField(help_text="Quand la mesure a été prise.")
    note = models.CharField(max_length=200, blank=True, help_text="Ex. à jeun, après le sport, le matin.")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mesure de santé"
        verbose_name_plural = "mesures de santé"
        ordering = ["-mesure_le"]

    def __str__(self):
        return f"{self.get_type_display()} : {self.valeur_affichee}"

    @property
    def unite(self):
        return self.REGLES[self.type][0] if self.type in self.REGLES else ""

    @property
    def valeur_affichee(self):
        texte = f"{self.valeur:g}" if self.valeur is not None else ""
        if self.type == self.Type.TENSION and self.valeur2 is not None:
            texte += f"/{self.valeur2:g}"
        return f"{texte} {self.unite}".strip()

    @property
    def alerte(self):
        """« haute », « basse » ou chaîne vide : simple repère, pas un diagnostic."""
        if self.type not in self.REGLES or self.valeur is None:
            return ""
        bas, haut = self.REGLES[self.type][3:]
        if haut is not None and self.valeur >= haut:
            return "haute"
        if bas is not None and self.valeur < bas:
            return "basse"
        if self.type == self.Type.TENSION and self.valeur2 is not None:
            if self.valeur2 >= self.DIASTOLE[3]:
                return "haute"
            if self.valeur2 < self.DIASTOLE[2]:
                return "basse"
        return ""

    def _doublon_existe(self):
        autres = Mesure.objects.filter(patient=self.patient, type=self.type, mesure_le=self.mesure_le)
        if self.pk:
            autres = autres.exclude(pk=self.pk)
        return autres.exists()

    def clean(self):
        super().clean()
        erreurs = {}
        if self.mesure_le:
            from django.utils import timezone

            self.mesure_le = self.mesure_le.replace(second=0, microsecond=0)  # précision : la minute
            if self.mesure_le > timezone.now():
                erreurs["mesure_le"] = "La date de la mesure ne peut pas être dans le futur."
        if self.type in self.REGLES and self.valeur is not None:
            unite, mini, maxi = self.REGLES[self.type][:3]
            if not mini <= self.valeur <= maxi:
                erreurs["valeur"] = f"Valeur improbable : entrez un nombre entre {mini:g} et {maxi:g} {unite}."
        if self.type == self.Type.TENSION:
            mini2, maxi2 = self.DIASTOLE[:2]
            if self.valeur2 is None:
                erreurs["valeur2"] = "Indiquez aussi le second chiffre de la tension (le plus petit)."
            elif not mini2 <= self.valeur2 <= maxi2:
                erreurs["valeur2"] = f"Valeur improbable : entrez un nombre entre {mini2:g} et {maxi2:g} mmHg."
            elif self.valeur is not None and self.valeur2 >= self.valeur:
                erreurs["valeur2"] = "Le second chiffre doit être plus petit que le premier."
        else:
            self.valeur2 = None  # le second chiffre n'existe que pour la tension
        if (
            "mesure_le" not in erreurs
            and self.mesure_le
            and self.type in self.REGLES
            and self.patient_id is not None
            and self._doublon_existe()
        ):
            erreurs["mesure_le"] = "Une mesure de ce type existe déjà pour cette minute."
        if erreurs:
            raise ValidationError(erreurs)


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

    def clean(self):
        super().clean()
        if self.drapeau_rouge and self.niveau_minimal is None:
            raise ValidationError(
                {"niveau_minimal": "Indiquez le niveau d'urgence imposé par ce drapeau rouge."}
            )
        if not self.drapeau_rouge and self.niveau_minimal is not None:
            raise ValidationError(
                {"niveau_minimal": "Le niveau minimal ne s'applique qu'à un drapeau rouge."}
            )

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


class AutoEvaluation(EmbeddedModel):
    """Ce que le patient dit ressentir, sur des échelles de 0 à 5 (voir echelles.py)."""

    douleur = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(NIVEAU_MIN), MaxValueValidator(NIVEAU_MAX)]
    )
    fievre = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(NIVEAU_MIN), MaxValueValidator(NIVEAU_MAX)]
    )
    respiration = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(NIVEAU_MIN), MaxValueValidator(NIVEAU_MAX)]
    )
    etat_general = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(NIVEAU_MIN), MaxValueValidator(NIVEAU_MAX)]
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
    auto_evaluation = EmbeddedModelField(AutoEvaluation, null=True, blank=True)
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

    def auto_evaluation_resume(self):
        """Valeurs non nulles de l'auto-évaluation, prêtes à afficher."""
        ae = self.auto_evaluation
        if not ae:
            return []
        resume = []
        for nom, echelle in ECHELLES.items():
            valeur = getattr(ae, nom, 0) or 0
            if valeur:
                resume.append(
                    {"nom": echelle["court"], "valeur": valeur, "libelle": echelle["niveaux"][valeur]}
                )
        return resume

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
