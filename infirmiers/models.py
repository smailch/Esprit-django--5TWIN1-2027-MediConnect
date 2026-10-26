import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django_mongodb_backend.fields import ArrayField, EmbeddedModelArrayField, EmbeddedModelField
from django_mongodb_backend.models import EmbeddedModel

from patients.models import ConstantesVitales, Consultation, Patient


class TypeSoin(models.TextChoices):
    """Soins réalisables à domicile : partagés par l'infirmier (ce qu'il pratique) et l'intervention (ce qui est demandé)."""

    INJECTION = "injection", "Injection"
    PANSEMENT = "pansement", "Pansement"
    PRELEVEMENT = "prelevement", "Prise de sang / prélèvement"
    PERFUSION = "perfusion", "Perfusion"
    SURVEILLANCE = "surveillance", "Surveillance des constantes"
    HYGIENE = "hygiene", "Soins d'hygiène"
    AUTRE = "autre", "Autre soin"


class NiveauAlerte(models.TextChoices):
    """Résultat de l'analyse du compte rendu (voir alertes.py) : un repère pour le médecin, pas un diagnostic."""

    RAS = "ras", "RAS"
    SURVEILLER = "surveiller", "À surveiller"
    SIGNALER = "signaler", "À signaler au médecin"


class SigneAlerte(EmbeddedModel):
    """Un signe d'alerte relevé dans le compte rendu, avec ce qui le justifie. Enregistré dans le document de
    l'intervention : l'historique reste stable même si le catalogue des signes change ensuite."""

    class Origine(models.TextChoices):
        TEXTE = "texte", "Note (règles)"
        IA = "ia", "Note (IA)"
        CONSTANTES = "constantes", "Constantes"
        EVOLUTION = "evolution", "Évolution"

    nom = models.CharField(max_length=100)
    extrait = models.CharField(max_length=200, help_text="Passage de la note ou valeurs qui justifient le signe.")
    gravite = models.CharField(max_length=10, choices=NiveauAlerte.choices)
    origine = models.CharField(max_length=12, choices=Origine.choices)


def _ville_normalisee(ville):
    """« tunis », « Tunis  » et « TUNIS » désignent la même ville."""
    return " ".join((ville or "").split()).casefold()


class Infirmier(models.Model):
    """Profil professionnel d'un compte de rôle « infirmier ». Le compte doit être validé par un administrateur
    (User.est_valide) avant de pouvoir accepter des interventions."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="infirmier"
    )
    telephone = models.CharField(max_length=20)
    numero_ordre = models.CharField(
        "Numéro d'inscription à l'Ordre", max_length=30, unique=True,
        help_text="Vérifié par l'administrateur avant la validation du compte.",
    )
    ville = models.CharField(max_length=100, help_text="Ville où l'infirmier exerce.")
    zones = ArrayField(
        models.CharField(max_length=100), default=list, blank=True,
        help_text="Autres villes où il accepte de se déplacer.",
    )
    soins = ArrayField(
        models.CharField(max_length=20, choices=TypeSoin.choices), default=list, blank=True,
        help_text="Soins pratiqués ; vide : tous les soins.",
    )
    disponible = models.BooleanField(default=True, help_text="Décochez pendant les congés : plus aucune nouvelle demande.")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "infirmier"
        verbose_name_plural = "infirmiers"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()

    @property
    def est_valide(self):
        return bool(self.user.est_valide and self.user.is_active)

    @property
    def villes_desservies(self):
        """Ville d'exercice puis zones, sans doublon."""
        villes = []
        for v in [self.ville, *self.zones]:
            v = " ".join((v or "").split())
            if v and _ville_normalisee(v) not in map(_ville_normalisee, villes):
                villes.append(v)
        return villes

    def dessert(self, ville):
        return _ville_normalisee(ville) in map(_ville_normalisee, self.villes_desservies)

    def pratique(self, type_soin):
        return not self.soins or type_soin in self.soins

    def clean(self):
        super().clean()
        self.ville = " ".join((self.ville or "").split())
        self.zones = [z for z in self.villes_desservies if _ville_normalisee(z) != _ville_normalisee(self.ville)]
        self.numero_ordre = (self.numero_ordre or "").strip().upper()
        if self.user_id is not None and getattr(self.user, "role", None) != "infirmier":
            raise ValidationError({"user": "Ce compte n'a pas le rôle « infirmier »."})


DUREE_PASSAGE = datetime.timedelta(minutes=30)  # temps réservé pour un passage (soin et trajet)


def passage_en_conflit(quand, autres):
    """Premier des passages `autres` (dates et heures) à moins de DUREE_PASSAGE de `quand`, ou None."""
    return next((autre for autre in sorted(autres) if abs(autre - quand) < DUREE_PASSAGE), None)


def prochain_creneau_libre(quand, autres):
    """`quand` s'il est libre, sinon la première heure qui suit sans chevauchement."""
    conflit = passage_en_conflit(quand, autres)
    while conflit is not None:
        quand = conflit + DUREE_PASSAGE
        conflit = passage_en_conflit(quand, autres)
    return quand


class InterventionQuerySet(models.QuerySet):
    def passages_autour(self, infirmier, quand, exclure=None):
        """Heures des passages déjà acceptés par cet infirmier dans les 12 heures autour de `quand`."""
        marge = datetime.timedelta(hours=12)
        passages = self.filter(
            infirmier=infirmier, statut=InterventionDomicile.Statut.ACCEPTEE,
            date_prevue__gt=quand - marge, date_prevue__lt=quand + marge,
        )
        if exclure is not None:
            passages = passages.exclude(pk=exclure)
        return [p.date_prevue for p in passages]

    def demandes_pour(self, infirmier):
        """Demandes en attente que cet infirmier peut accepter : dans ses villes et parmi ses soins."""
        zone = models.Q()
        for ville in infirmier.villes_desservies:
            zone |= models.Q(ville__iexact=ville)
        if not zone:
            return self.none()
        demandes = self.filter(zone, statut=InterventionDomicile.Statut.DEMANDEE, infirmier__isnull=True)
        if infirmier.soins:
            demandes = demandes.filter(type_soin__in=infirmier.soins)
        return demandes

    def de(self, infirmier):
        return self.filter(infirmier=infirmier)


class InterventionDomicile(models.Model):
    """Un soin à domicile, de la demande au compte rendu.

    Cycle de vie : demandée (sans infirmier) → acceptée (un infirmier de la zone l'a planifiée) → réalisée
    (compte rendu saisi). Elle peut être annulée tant qu'elle n'est pas réalisée."""

    class Statut(models.TextChoices):
        DEMANDEE = "demandee", "Demandée"
        ACCEPTEE = "acceptee", "Acceptée"
        REALISEE = "realisee", "Réalisée"
        ANNULEE = "annulee", "Annulée"

    class Moment(models.TextChoices):
        MATIN = "matin", "Matin"
        APRES_MIDI = "apres_midi", "Après-midi"
        INDIFFERENT = "indifferent", "Indifférent"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="interventions")
    infirmier = models.ForeignKey(
        Infirmier, on_delete=models.SET_NULL, null=True, blank=True, related_name="interventions"
    )
    consultation = models.ForeignKey(
        Consultation, on_delete=models.SET_NULL, null=True, blank=True, related_name="interventions",
        help_text="Consultation au cours de laquelle le soin a été prescrit, s'il y en a une.",
    )
    type_soin = models.CharField("Type de soin", max_length=20, choices=TypeSoin.choices)
    description = models.TextField(
        "Détail du soin", blank=True, help_text="Ex. injection d'anticoagulant, pansement de la jambe gauche."
    )
    adresse = models.CharField(max_length=255)
    ville = models.CharField(max_length=100)
    date_souhaitee = models.DateField("Date souhaitée")
    moment = models.CharField(max_length=15, choices=Moment.choices, default=Moment.INDIFFERENT)

    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.DEMANDEE)
    date_prevue = models.DateTimeField("Passage prévu", null=True, blank=True)
    acceptee_le = models.DateTimeField(null=True, blank=True)
    realisee_le = models.DateTimeField(null=True, blank=True)
    compte_rendu = models.TextField("Compte rendu de soin", blank=True)
    constantes = EmbeddedModelField(ConstantesVitales, null=True, blank=True)
    niveau_alerte = models.CharField(
        "Niveau d'alerte", max_length=10, choices=NiveauAlerte.choices, blank=True, help_text="Vide : pas encore analysé."
    )
    signes_alerte = EmbeddedModelArrayField(SigneAlerte, default=list, blank=True)
    analyse_ia = models.CharField(
        "Statut de l'IA", max_length=20, blank=True, help_text="« ok » si l'IA a lu la note, sinon la raison (désactivée, délai…)."
    )
    annulee_le = models.DateTimeField(null=True, blank=True)
    motif_annulation = models.CharField("Motif d'annulation", max_length=200, blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    objects = InterventionQuerySet.as_manager()

    class Meta:
        verbose_name = "intervention à domicile"
        verbose_name_plural = "interventions à domicile"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.get_type_soin_display()} – {self.patient} ({self.get_statut_display().lower()})"

    @property
    def est_modifiable(self):
        """Une intervention réalisée ou annulée est archivée : on ne la change plus."""
        return self.statut in (self.Statut.DEMANDEE, self.Statut.ACCEPTEE)

    @property
    def a_cloturer(self):
        """Passage prévu dépassé sans compte rendu."""
        return self.statut == self.Statut.ACCEPTEE and self.date_prevue is not None and self.date_prevue <= timezone.now()

    @property
    def heure_conseillee(self):
        """Heure proposée par défaut à l'infirmier qui accepte : selon le moment souhaité par le patient."""
        return {self.Moment.MATIN: (9, 0), self.Moment.APRES_MIDI: (14, 0)}.get(self.moment, (10, 0))

    def clean(self):
        super().clean()
        erreurs = {}
        self.ville = " ".join((self.ville or "").split())
        aujourdhui = timezone.localdate()

        # Seulement à la création : une demande restée sans réponse garde sa date, même dépassée.
        if self._state.adding and self.date_souhaitee and self.date_souhaitee < aujourdhui:
            erreurs["date_souhaitee"] = "La date souhaitée ne peut pas être dans le passé."

        if self.statut in (self.Statut.ACCEPTEE, self.Statut.REALISEE):
            if self.infirmier_id is None:
                erreurs["infirmier"] = "Une intervention acceptée doit avoir un infirmier."
            if self.date_prevue is None:
                erreurs["date_prevue"] = "Indiquez l'heure de passage prévue."

        if self.statut == self.Statut.REALISEE:
            if not (self.compte_rendu or "").strip():
                erreurs["compte_rendu"] = "Le compte rendu est obligatoire pour clore l'intervention."
            if self.realisee_le and self.realisee_le > timezone.now():
                erreurs["realisee_le"] = "Le soin ne peut pas être réalisé dans le futur."

        if self.statut == self.Statut.ANNULEE and not (self.motif_annulation or "").strip():
            erreurs["motif_annulation"] = "Indiquez pourquoi l'intervention est annulée."

        if erreurs:
            raise ValidationError(erreurs)

    # --- Étapes du cycle de vie : chacune vérifie l'état de départ puis valide l'objet complet.
    # Elles n'enregistrent pas : la vue appelle save() ensuite. ---

    def _passer(self, **valeurs):
        """Applique les valeurs puis valide ; en cas de refus, l'objet retrouve son état précédent."""
        avant = {champ: getattr(self, champ) for champ in valeurs}
        for champ, valeur in valeurs.items():
            setattr(self, champ, valeur)
        try:
            self.full_clean()
        except ValidationError:
            for champ, valeur in avant.items():
                setattr(self, champ, valeur)
            raise

    def accepter(self, infirmier, date_prevue):
        """Règles vérifiées au moment de l'acceptation seulement : si l'infirmier change ensuite de zone ou de
        soins, ses interventions déjà acceptées restent valables."""
        if self.statut != self.Statut.DEMANDEE:
            raise ValidationError("Seule une demande en attente peut être acceptée.")
        if not infirmier.est_valide:
            raise ValidationError("Votre compte doit être validé par un administrateur.")
        if not infirmier.disponible:
            raise ValidationError("Vous êtes indiqué comme indisponible.")
        if not infirmier.dessert(self.ville):
            raise ValidationError(f"Vous ne vous déplacez pas à {self.ville}.")
        if not infirmier.pratique(self.type_soin):
            raise ValidationError("Vous ne pratiquez pas ce soin.")
        if date_prevue < timezone.now():
            raise ValidationError({"date_prevue": "Le passage prévu ne peut pas être dans le passé."})
        self._passer(infirmier=infirmier, date_prevue=date_prevue, statut=self.Statut.ACCEPTEE, acceptee_le=timezone.now())

    def replanifier(self, date_prevue):
        if self.statut != self.Statut.ACCEPTEE:
            raise ValidationError("Seule une intervention acceptée peut être replanifiée.")
        if date_prevue < timezone.now():
            raise ValidationError({"date_prevue": "Le passage prévu ne peut pas être dans le passé."})
        self._passer(date_prevue=date_prevue)

    def liberer(self):
        """L'infirmier se désiste : la demande retourne aux infirmiers de la zone."""
        if self.statut != self.Statut.ACCEPTEE:
            raise ValidationError("Seule une intervention acceptée peut être rendue.")
        self._passer(infirmier=None, date_prevue=None, acceptee_le=None, statut=self.Statut.DEMANDEE)

    def terminer(self, compte_rendu, constantes=None, realisee_le=None, analyse=None):
        """analyse : résultat de ia_soin.analyser() (niveau, signes, statut_ia), enregistré avec le compte rendu."""
        if self.statut != self.Statut.ACCEPTEE:
            raise ValidationError("Seule une intervention acceptée peut être terminée.")
        valeurs = {
            "compte_rendu": (compte_rendu or "").strip(),
            "constantes": constantes,
            "realisee_le": realisee_le or timezone.now(),
            "statut": self.Statut.REALISEE,
        }
        if analyse is not None:
            valeurs.update(
                niveau_alerte=analyse.niveau,
                signes_alerte=[
                    SigneAlerte(nom=s.nom, extrait=s.extrait[:200], gravite=s.gravite, origine=s.origine) for s in analyse.signes
                ],
                analyse_ia=analyse.statut_ia,
            )
        self._passer(**valeurs)

    @property
    def a_signaler(self):
        return self.niveau_alerte == NiveauAlerte.SIGNALER

    def releves(self):
        """{nom: valeur} des constantes de ce passage (pour comparer les passages entre eux)."""
        if self.constantes is None:
            return {}
        noms = ("temperature", "tension_systolique", "tension_diastolique", "frequence_cardiaque", "saturation_oxygene")
        return {n: float(getattr(self.constantes, n)) for n in noms if getattr(self.constantes, n) is not None}

    def annuler(self, motif):
        if not self.est_modifiable:
            raise ValidationError("Cette intervention est déjà close.")
        self._passer(motif_annulation=(motif or "").strip(), statut=self.Statut.ANNULEE, annulee_le=timezone.now())
