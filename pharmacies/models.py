import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from patients.models import Consultation, Patient

DUREE_VALIDITE_JOURS = 90  # une ordonnance classique reste valable trois mois
MAX_LIGNES = 15  # au-delà, c'est presque toujours une erreur de saisie

telephone_valide = RegexValidator(r"^\+?[0-9][0-9 ]{6,18}[0-9]$", "Numéro de téléphone invalide (chiffres et espaces seulement).")


class Pharmacie(models.Model):
    """Une officine. Son compte (rôle « pharmacie ») doit être validé par un administrateur
    avant de pouvoir traiter des ordonnances (voir permissions.py)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pharmacie")
    nom = models.CharField(max_length=150)
    adresse = models.CharField(max_length=255)
    ville = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20, validators=[telephone_valide])
    horaires = models.CharField(max_length=200, blank=True, help_text="Ex. du lundi au samedi, 8 h – 20 h.")
    de_garde = models.BooleanField(default=False, help_text="Ouverte la nuit, le dimanche et les jours fériés.")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ville", "nom"]
        verbose_name = "pharmacie"
        verbose_name_plural = "pharmacies"

    def __str__(self):
        return self.nom

    def clean(self):
        super().clean()
        self.nom = " ".join((self.nom or "").split())
        if self.user_id is not None and self.user.role != self.user.Role.PHARMACIE:
            raise ValidationError({"user": "Ce compte n'a pas le rôle « pharmacie »."})


class Medicament(models.Model):
    """Un médicament du stock d'UNE pharmacie (chaque officine gère le sien).

    La rupture n'est pas une case à cocher : un médicament est en rupture quand sa quantité tombe à zéro."""

    class Forme(models.TextChoices):
        COMPRIME = "comprime", "Comprimé"
        GELULE = "gelule", "Gélule"
        SIROP = "sirop", "Sirop"
        SACHET = "sachet", "Sachet"
        INHALATEUR = "inhalateur", "Inhalateur"
        INJECTABLE = "injectable", "Injectable"
        CREME = "creme", "Crème ou pommade"
        AUTRE = "autre", "Autre"

    RUPTURE, STOCK_BAS, DISPONIBLE = "rupture", "bas", "ok"

    pharmacie = models.ForeignKey(Pharmacie, on_delete=models.CASCADE, related_name="medicaments")
    nom = models.CharField(max_length=100, help_text="Nom commercial ou générique (ex. Doliprane, Amoxicilline Biogaran).")
    principe_actif = models.CharField(max_length=100, blank=True, help_text="La molécule (ex. paracétamol) : sert à trouver les équivalents.")
    dosage = models.CharField(max_length=50, blank=True, help_text="Ex. 1 g, 500 mg, 100 µg.")
    forme = models.CharField(max_length=20, choices=Forme.choices, default=Forme.COMPRIME)
    # MinValueValidator explicite : avec MongoDB, « Positive » ne suffit pas à refuser une valeur négative côté modèle.
    quantite = models.PositiveIntegerField(
        "Quantité en stock", default=0, validators=[MinValueValidator(0)], help_text="Nombre de boîtes. À zéro, le médicament est en rupture."
    )
    seuil_alerte = models.PositiveSmallIntegerField(
        "Seuil d'alerte", default=5, validators=[MinValueValidator(0)],
        help_text="En dessous ou à ce nombre de boîtes, le stock est signalé comme bas.",
    )
    prix = models.DecimalField("Prix (DT)", max_digits=8, decimal_places=3, null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "dosage"]
        verbose_name = "médicament"
        verbose_name_plural = "médicaments"
        indexes = [models.Index(fields=["pharmacie", "quantite"])]

    def __str__(self):
        return f"{self.nom} {self.dosage}".strip()

    @property
    def etat(self):
        if self.quantite == 0:
            return self.RUPTURE
        return self.STOCK_BAS if self.quantite <= self.seuil_alerte else self.DISPONIBLE

    @property
    def est_en_rupture(self):
        return self.etat == self.RUPTURE

    @property
    def libelle_etat(self):
        return {self.RUPTURE: "Rupture", self.STOCK_BAS: "Stock bas", self.DISPONIBLE: "En stock"}[self.etat]

    def _doublon_existe(self):
        """Le même médicament (nom et dosage, majuscules ignorées) existe-t-il déjà dans le stock de cette pharmacie ?"""
        autres = Medicament.objects.filter(pharmacie=self.pharmacie, nom__iexact=self.nom, dosage__iexact=self.dosage)
        if self.pk:
            autres = autres.exclude(pk=self.pk)
        return autres.exists()

    def clean(self):
        super().clean()
        self.nom = " ".join((self.nom or "").split())
        self.principe_actif = " ".join((self.principe_actif or "").split()).lower()
        self.dosage = " ".join((self.dosage or "").split())
        if self.prix is not None and self.prix < 0:
            raise ValidationError({"prix": "Le prix ne peut pas être négatif."})
        if self.nom and self.pharmacie_id is not None and self._doublon_existe():
            raise ValidationError({"nom": "Ce médicament (même nom et même dosage) est déjà dans votre stock : modifiez sa quantité."})


class Ordonnance(models.Model):
    """Ordonnance rédigée à la suite d'une consultation, puis transmise par le patient à la pharmacie de son choix.

    Cycle de vie : émise -> transmise -> en préparation -> prête -> délivrée (ou annulée par le prescripteur)."""

    class Statut(models.TextChoices):
        EMISE = "emise", "Émise"
        TRANSMISE = "transmise", "Transmise à la pharmacie"
        EN_PREPARATION = "en_preparation", "En préparation"
        PRETE = "prete", "Prête à retirer"
        DELIVREE = "delivree", "Délivrée"
        ANNULEE = "annulee", "Annulée"

    # Ce que la pharmacie peut faire : une seule étape à la fois, jamais de retour en arrière.
    SUIVANT = {
        Statut.TRANSMISE: Statut.EN_PREPARATION,
        Statut.EN_PREPARATION: Statut.PRETE,
        Statut.PRETE: Statut.DELIVREE,
    }
    PARCOURS = [Statut.EMISE, Statut.TRANSMISE, Statut.EN_PREPARATION, Statut.PRETE, Statut.DELIVREE]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="ordonnances")
    consultation = models.ForeignKey(
        Consultation, on_delete=models.SET_NULL, null=True, blank=True, related_name="ordonnances"
    )
    pharmacie = models.ForeignKey(
        Pharmacie, on_delete=models.SET_NULL, null=True, blank=True, related_name="ordonnances"
    )
    prescripteur_nom = models.CharField(max_length=150)
    medicaments = models.TextField(
        "Médicaments", help_text="Un médicament par ligne : nom, dosage, posologie et durée (ex. Amoxicilline 1 g, 1 comprimé matin et soir, 7 jours)."
    )
    instructions = models.TextField("Instructions", blank=True, help_text="Conseils au patient et au pharmacien.")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EMISE)
    date_emission = models.DateField("Date de l'ordonnance", default=timezone.localdate)
    valide_jusqu_au = models.DateField(
        "Valable jusqu'au", null=True, blank=True, help_text=f"Laissez vide : {DUREE_VALIDITE_JOURS} jours après la date de l'ordonnance."
    )
    note_pharmacien = models.CharField("Note de la pharmacie", max_length=300, blank=True)
    delivree_le = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_emission", "-cree_le"]
        verbose_name = "ordonnance"
        verbose_name_plural = "ordonnances"
        indexes = [models.Index(fields=["pharmacie", "statut"]), models.Index(fields=["patient", "statut"])]

    def __str__(self):
        return f"Ordonnance {self.reference} – {self.patient}"

    @property
    def reference(self):
        """Référence courte lisible au comptoir (fin de l'identifiant MongoDB)."""
        return f"ORD-{str(self.pk)[-6:].upper()}" if self.pk else "ORD-?"

    @property
    def lignes(self):
        return [ligne.strip(" -•\t") for ligne in (self.medicaments or "").splitlines() if ligne.strip(" -•\t")]

    @property
    def est_expiree(self):
        return bool(self.valide_jusqu_au) and self.valide_jusqu_au < timezone.localdate()

    @property
    def est_modifiable(self):
        """Le prescripteur corrige tant que la pharmacie n'a pas commencé la préparation."""
        return self.statut in (self.Statut.EMISE, self.Statut.TRANSMISE)

    @property
    def est_supprimable(self):
        """Une ordonnance préparée ou délivrée est gardée : c'est la trace de ce qui a été remis au patient."""
        return self.statut in (self.Statut.EMISE, self.Statut.TRANSMISE, self.Statut.ANNULEE)

    @property
    def est_annulable(self):
        return self.statut not in (self.Statut.DELIVREE, self.Statut.ANNULEE)

    @property
    def est_transmissible(self):
        """Le patient choisit (ou change) sa pharmacie tant que la préparation n'a pas commencé."""
        return self.statut in (self.Statut.EMISE, self.Statut.TRANSMISE) and not self.est_expiree

    @property
    def est_en_traitement(self):
        """Reçue par la pharmacie et pas encore prête : c'est le moment de signaler une rupture."""
        return self.statut in (self.Statut.TRANSMISE, self.Statut.EN_PREPARATION)

    @property
    def statut_suivant(self):
        return self.SUIVANT.get(self.statut)

    @property
    def etape(self):
        """Position dans le parcours (0 à 4), pour la barre d'étapes ; None si annulée."""
        return self.PARCOURS.index(self.statut) if self.statut in self.PARCOURS else None

    def appliquer_validite_par_defaut(self):
        if self.valide_jusqu_au is None and self.date_emission:
            self.valide_jusqu_au = self.date_emission + datetime.timedelta(days=DUREE_VALIDITE_JOURS)

    def clean(self):
        super().clean()
        erreurs = {}
        lignes = self.lignes
        if not lignes:
            erreurs["medicaments"] = "Indiquez au moins un médicament."
        elif len(lignes) > MAX_LIGNES:
            erreurs["medicaments"] = f"Une ordonnance contient au plus {MAX_LIGNES} lignes."
        else:
            self.medicaments = "\n".join(lignes)  # puces et lignes vides retirées
        if self.date_emission and self.date_emission > timezone.localdate():
            erreurs["date_emission"] = "La date de l'ordonnance ne peut pas être dans le futur."
        if self.date_emission and self.valide_jusqu_au and self.valide_jusqu_au < self.date_emission:
            erreurs["valide_jusqu_au"] = "La fin de validité doit suivre la date de l'ordonnance."
        if self.consultation_id is not None and self.patient_id is not None and self.consultation.patient_id != self.patient_id:
            erreurs["consultation"] = "Cette consultation concerne un autre patient."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.appliquer_validite_par_defaut()
        super().save(*args, **kwargs)

    def avancer(self):
        """Passe à l'étape suivante (action de la pharmacie). Lève ValueError si c'est impossible."""
        suivant = self.statut_suivant
        if suivant is None:
            raise ValueError("Cette ordonnance ne peut plus avancer.")
        if suivant == self.Statut.DELIVREE and self.est_expiree:
            raise ValueError("Cette ordonnance a expiré : elle ne peut pas être délivrée.")
        self.statut = suivant
        champs = ["statut", "modifie_le"]
        if suivant == self.Statut.DELIVREE:
            self.delivree_le = timezone.now()
            champs.append("delivree_le")
        self.save(update_fields=champs)
        return suivant
