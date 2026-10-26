import datetime

from django import forms
from django.db.models import Q
from django.utils import timezone

from medecins import annuaire
from patients.models import Allergie, Consultation, Patient, ReglageTriage, Triage

from .stats import LIBELLES_NIVEAU


class FiltreRendezVousForm(forms.Form):
    """Recherche et filtres de la liste des rendez-vous (envoyés en GET)."""

    q = forms.CharField(label="Rechercher", required=False, max_length=100)
    statut = forms.ChoiceField(
        label="Statut", required=False, choices=[("", "Tous")] + list(Triage.Statut.choices)
    )
    niveau = forms.ChoiceField(
        label="Niveau d'urgence",
        required=False,
        choices=[("", "Tous")] + [(str(n), f"{n} – {nom}") for n, nom in LIBELLES_NIVEAU.items()],
    )
    medecin = forms.ChoiceField(label="Médecin", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medecin"].choices = [("", "Tous")] + [(m["id"], m["nom"]) for m in annuaire.tous()]
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "field"


class MajRendezVousForm(forms.ModelForm):
    """Ce que l'administrateur peut modifier : le statut et le niveau requalifié.
    Le score, le niveau calculé et les déclarations du patient restent intacts."""

    class Meta:
        model = Triage
        fields = ("statut", "niveau_medecin")
        labels = {
            "statut": "Statut de la demande",
            "niveau_medecin": "Niveau requalifié par le médecin",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["niveau_medecin"].required = False
        self.fields["niveau_medecin"].help_text = (
            "Laissez vide pour garder le niveau calculé par le triage."
        )
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "field"

    def save(self, commit=True):
        ancien = self.initial.get("statut")
        triage = super().save(commit=commit)
        # Une demande prise en charge devant des demandes plus anciennes : chacune compte un dépassement.
        if commit and ancien != Triage.Statut.EN_CONSULTATION and triage.statut == Triage.Statut.EN_CONSULTATION:
            triage.enregistrer_depassements()
        return triage


class ReglageTriageForm(forms.ModelForm):
    """Délais cibles, plafond de dépassements et durée de consultation de la file d'attente."""

    class Meta:
        model = ReglageTriage
        exclude = ("modifie_le",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "field"


def consultation_pour(triage):
    """Le compte rendu de cette demande, ou un compte rendu vierge à remplir (motif prérempli avec les symptômes)."""
    existante = Consultation.objects.filter(triage=triage).first()
    if existante is not None:
        return existante
    motif = ", ".join(s.nom for s in triage.symptomes or [])[:200]
    return Consultation(
        patient=triage.patient, triage=triage, medecin_nom=triage.medecin_nom,
        medecin_specialite=triage.medecin_specialite, motif=motif, date=timezone.now(),
    )


class ConsultationForm(forms.ModelForm):
    """Compte rendu saisi en terminant un rendez-vous : il apparaît ensuite dans le dossier du patient."""

    class Meta:
        model = Consultation
        fields = ("date", "motif", "resume", "diagnostic", "prescription", "recommandations")
        widgets = {
            "date": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "resume": forms.Textarea(attrs={"rows": 5}),
            "prescription": forms.Textarea(attrs={"rows": 3}),
            "recommandations": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "field"


def _il_y_a_ans(jour, annees):
    try:
        return jour.replace(year=jour.year - annees)
    except ValueError:  # 29 février d'une année non bissextile
        return jour.replace(year=jour.year - annees, day=28)


class FiltrePatientForm(forms.Form):
    """Recherche et filtres de la liste des patients (envoyés en GET). Le même filtre sert à l'export CSV."""

    COMPTES = (("", "Tous"), ("actif", "Actifs"), ("desactive", "Désactivés"))

    q = forms.CharField(label="Nom, e-mail, téléphone ou ville", required=False, max_length=100)
    sexe = forms.ChoiceField(label="Sexe", required=False, choices=[("", "Tous")] + list(Patient.Sexe.choices))
    ville = forms.ChoiceField(label="Ville", required=False, choices=[("", "Toutes")])
    age_min = forms.IntegerField(label="Âge minimum", required=False, min_value=0, max_value=130)
    age_max = forms.IntegerField(label="Âge maximum", required=False, min_value=0, max_value=130)
    compte = forms.ChoiceField(label="Compte", required=False, choices=COMPTES)
    allergie_severe = forms.BooleanField(label="Avec une allergie sévère", required=False)

    def __init__(self, *args, villes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ville"].choices = [("", "Toutes")] + [(v, v) for v in villes]
        for nom, champ in self.fields.items():
            if nom != "allergie_severe":
                champ.widget.attrs["class"] = "field"

    def clean(self):
        donnees = super().clean()
        mini, maxi = donnees.get("age_min"), donnees.get("age_max")
        if mini is not None and maxi is not None and mini > maxi:
            self.add_error("age_max", "L'âge maximum doit être supérieur ou égal à l'âge minimum.")
        return donnees

    def appliquer(self, patients, aujourdhui=None):
        """Restreint une liste de patients (QuerySet) selon les filtres choisis. À appeler après is_valid()."""
        d = self.cleaned_data
        aujourdhui = aujourdhui or timezone.localdate()
        q = (d.get("q") or "").strip()
        if q:
            patients = patients.filter(
                Q(user__last_name__icontains=q) | Q(user__first_name__icontains=q) | Q(user__email__icontains=q)
                | Q(telephone__icontains=q) | Q(ville__icontains=q)
            )
        if d.get("sexe"):
            patients = patients.filter(sexe=d["sexe"])
        if d.get("ville"):
            patients = patients.filter(ville__iexact=d["ville"])
        if d.get("age_min") is not None:  # 30 ans révolus au moins : né il y a 30 ans ou plus
            patients = patients.filter(date_naissance__lte=_il_y_a_ans(aujourdhui, d["age_min"]))
        if d.get("age_max") is not None:  # 40 ans au plus : pas encore 41 ans
            patients = patients.filter(date_naissance__gt=_il_y_a_ans(aujourdhui, d["age_max"] + 1))
        if d.get("compte") == "actif":
            patients = patients.filter(user__is_active=True)
        elif d.get("compte") == "desactive":
            patients = patients.filter(user__is_active=False)
        if d.get("allergie_severe"):
            avec = set(Allergie.objects.filter(gravite=Allergie.Gravite.SEVERE, active=True).values_list("patient", flat=True))
            patients = patients.filter(pk__in=avec)
        return patients

    def parametres(self):
        """Les filtres actifs, prêts pour une adresse (pagination, export) : {nom: valeur}."""
        if not self.is_valid():
            return {}
        actifs = {}
        for nom, valeur in self.cleaned_data.items():
            if valeur in (None, "", False):
                continue
            actifs[nom] = "on" if valeur is True else str(valeur).strip()
        return actifs


class FiltreMedecinForm(forms.Form):
    """Recherche et filtres de la liste des médecins (envoyés en GET)."""

    COMPTES = (("", "Tous"), ("actif", "Actifs"), ("desactive", "Désactivés"))
    VALIDATIONS = (("", "Toutes"), ("valide", "Validés"), ("attente", "En attente"))
    PRESENCES = (("", "Toutes"), ("ouvert", "Prennent des rendez-vous"), ("ferme", "Absents"))

    q = forms.CharField(label="Nom, e-mail, téléphone, spécialité ou ville", required=False, max_length=100)
    specialite = forms.ChoiceField(label="Spécialité", required=False, choices=[("", "Toutes")])
    ville = forms.ChoiceField(label="Ville", required=False, choices=[("", "Toutes")])
    compte = forms.ChoiceField(label="Compte", required=False, choices=COMPTES)
    validation = forms.ChoiceField(label="Validation", required=False, choices=VALIDATIONS)
    presence = forms.ChoiceField(label="Prise de rendez-vous", required=False, choices=PRESENCES)

    def __init__(self, *args, specialites=(), villes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["specialite"].choices = [("", "Toutes")] + [(s, s) for s in specialites]
        self.fields["ville"].choices = [("", "Toutes")] + [(v, v) for v in villes]
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "field"

    def appliquer(self, medecins):
        """Restreint la liste des médecins selon les filtres choisis. À appeler après is_valid()."""
        d = self.cleaned_data
        q = (d.get("q") or "").strip()
        if q:
            medecins = medecins.filter(
                Q(user__last_name__icontains=q) | Q(user__first_name__icontains=q) | Q(user__email__icontains=q)
                | Q(telephone__icontains=q) | Q(ville__icontains=q) | Q(specialite__icontains=q)
            )
        if d.get("specialite"):
            medecins = medecins.filter(specialite=d["specialite"])
        if d.get("ville"):
            medecins = medecins.filter(ville__iexact=d["ville"])
        if d.get("compte") == "actif":
            medecins = medecins.filter(user__is_active=True)
        elif d.get("compte") == "desactive":
            medecins = medecins.filter(user__is_active=False)
        if d.get("validation") == "valide":
            medecins = medecins.filter(user__est_valide=True)
        elif d.get("validation") == "attente":
            medecins = medecins.filter(user__est_valide=False)
        if d.get("presence") == "ouvert":
            medecins = medecins.filter(disponible=True)
        elif d.get("presence") == "ferme":
            medecins = medecins.filter(disponible=False)
        return medecins

    def parametres(self):
        if not self.is_valid():
            return {}
        return {nom: str(valeur).strip() for nom, valeur in self.cleaned_data.items() if valeur not in (None, "")}
