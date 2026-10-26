from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from core.forms import MESSAGE_EMAIL_UTILISE, StyledFormMixin, email_deja_utilise
from patients.models import Consultation, Triage

from .horaires import JOURS, analyser_jour, texte_du_jour
from .models import Medecin, PlageHoraire, Prescription

User = get_user_model()


def composer_prescription(ordonnance, examens, soins):
    """Texte unique recopié dans le dossier du patient."""
    blocs = []
    for titre, texte in (
        ("Ordonnance", ordonnance),
        ("Examens de laboratoire", examens),
        ("Soins à domicile", soins),
    ):
        texte = (texte or "").strip()
        if texte:
            blocs.append(f"{titre}\n{texte}")
    return "\n\n".join(blocs)


def consultation_pour(triage, medecin):
    """Le compte rendu de cette demande, ou un compte rendu vierge (motif prérempli avec les symptômes)."""
    existante = Consultation.objects.filter(triage=triage).first()
    if existante is not None:
        return existante
    motif = ", ".join(s.nom for s in triage.symptomes or [])[:200]
    return Consultation(
        patient=triage.patient,
        triage=triage,
        medecin_nom=medecin.nom_affiche,
        medecin_specialite=medecin.specialite,
        motif=motif,
        date=timezone.now(),
    )


class _HorairesMixin:
    """Sept champs texte, un par jour, convertis en plages embarquées."""

    def _ajouter_champs_horaires(self, plages=()):
        for jour, libelle in JOURS:
            self.fields[f"plage_{jour}"] = forms.CharField(
                label=libelle,
                required=False,
                initial=texte_du_jour(plages, jour),
                help_text="Ex. 9-12, 14-17. Laissez vide si vous ne consultez pas ce jour-là.",
            )

    def _plages_nettoyees(self):
        plages = []
        for jour, _libelle in JOURS:
            try:
                creneaux = analyser_jour(self.cleaned_data.get(f"plage_{jour}", ""))
            except ValueError as erreur:
                self.add_error(f"plage_{jour}", str(erreur))
                continue
            plages.extend(PlageHoraire(jour=jour, debut=debut, fin=fin) for debut, fin in creneaux)
        return plages


class InscriptionMedecinForm(_HorairesMixin, StyledFormMixin, UserCreationForm):
    """Crée le compte (rôle médecin, en attente de validation) et son profil."""

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    email = forms.EmailField(label="Adresse e-mail")
    specialite = forms.CharField(label="Spécialité", max_length=100)
    ville = forms.CharField(label="Ville", max_length=100)
    telephone = forms.CharField(label="Téléphone", max_length=20)
    numero_ordre = forms.CharField(label="Numéro d'ordre", max_length=50, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {"username": "Identifiant"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Mot de passe"
        self.fields["password2"].label = "Confirmation du mot de passe"
        self._ajouter_champs_horaires()
        self._style_fields()
        self._autocompleter(
            username="username",
            first_name="given-name",
            last_name="family-name",
            email="email",
            telephone="tel",
            password1="new-password",
            password2="new-password",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_deja_utilise(email):
            raise forms.ValidationError(MESSAGE_EMAIL_UTILISE)
        return email

    def clean(self):
        nettoye = super().clean()
        self._plages = self._plages_nettoyees()
        return nettoye

    def _code_libre(self, username):
        base = (slugify(username) or "medecin")[:40]
        code, numero = base, 2
        while Medecin.objects.filter(code=code).exists():
            code = f"{base}-{numero}"[:50]
            numero += 1
        return code

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.MEDECIN
        user.est_valide = False
        user.save()
        Medecin.objects.create(
            user=user,
            code=self._code_libre(user.username),
            specialite=self.cleaned_data["specialite"],
            ville=self.cleaned_data["ville"],
            telephone=self.cleaned_data["telephone"],
            numero_ordre=self.cleaned_data.get("numero_ordre", ""),
            disponible=True,
            plages=self._plages,
        )
        return user


class ProfilMedecinForm(_HorairesMixin, StyledFormMixin, forms.ModelForm):
    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    email = forms.EmailField(label="Adresse e-mail")

    class Meta:
        model = Medecin
        fields = ("specialite", "ville", "telephone", "numero_ordre", "disponible", "presentation")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        utilisateur = self.instance.user
        self.fields["first_name"].initial = utilisateur.first_name
        self.fields["last_name"].initial = utilisateur.last_name
        self.fields["email"].initial = utilisateur.email
        self._ajouter_champs_horaires(self.instance.plages)
        self._style_fields()
        self._autocompleter(first_name="given-name", last_name="family-name", email="email", telephone="tel")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_deja_utilise(email, exclure_pk=self.instance.user_id):
            raise forms.ValidationError(MESSAGE_EMAIL_UTILISE)
        return email

    def clean(self):
        nettoye = super().clean()
        self._plages = self._plages_nettoyees()
        return nettoye

    @transaction.atomic
    def save(self, commit=True):
        medecin = super().save(commit=False)
        medecin.plages = self._plages
        utilisateur = medecin.user
        utilisateur.first_name = self.cleaned_data["first_name"]
        utilisateur.last_name = self.cleaned_data["last_name"]
        utilisateur.email = self.cleaned_data["email"]
        if commit:
            utilisateur.save()
            medecin.save()
        return medecin


class RequalificationForm(StyledFormMixin, forms.Form):
    """Le médecin garde la décision finale sur le niveau d'urgence."""

    niveau = forms.TypedChoiceField(
        label="Niveau d'urgence",
        choices=Triage.Niveau.choices,
        coerce=int,
        help_text="Ce niveau remplace celui proposé par le triage. Le patient reste informé.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class CompteRenduForm(StyledFormMixin, forms.ModelForm):
    """Compte rendu, puis les trois prescriptions qui partent vers les autres modules."""

    ordonnance = forms.CharField(
        label="Ordonnance",
        required=False,
        widget=forms.Textarea,
        help_text="Médicaments et posologie. La pharmacie s'appuiera sur ce texte.",
    )
    examens = forms.CharField(
        label="Examens de laboratoire",
        required=False,
        widget=forms.Textarea,
        help_text="Analyses demandées et ce que le laboratoire doit chercher.",
    )
    soins = forms.CharField(
        label="Soins à domicile",
        required=False,
        widget=forms.Textarea,
        help_text="Soins ou prélèvement à confier à un infirmier.",
    )

    class Meta:
        model = Consultation
        fields = ("date", "motif", "resume", "diagnostic", "recommandations")
        widgets = {"date": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        self.fields["resume"].label = "Compte rendu"
        if self.instance.pk:
            textes = {acte.type: acte.contenu for acte in self.instance.actes.all()}
            self.fields["ordonnance"].initial = textes.get(Prescription.Type.ORDONNANCE, "")
            self.fields["examens"].initial = textes.get(Prescription.Type.EXAMEN, "")
            self.fields["soins"].initial = textes.get(Prescription.Type.SOIN, "")
        self._style_fields()

    def save(self, commit=True):
        consultation = super().save(commit=False)
        consultation.prescription = composer_prescription(
            self.cleaned_data.get("ordonnance"),
            self.cleaned_data.get("examens"),
            self.cleaned_data.get("soins"),
        )
        if commit:
            consultation.save()
            self.enregistrer_actes(consultation)
        return consultation

    def enregistrer_actes(self, consultation):
        textes = {
            Prescription.Type.ORDONNANCE: self.cleaned_data.get("ordonnance"),
            Prescription.Type.EXAMEN: self.cleaned_data.get("examens"),
            Prescription.Type.SOIN: self.cleaned_data.get("soins"),
        }
        for type_acte, contenu in textes.items():
            contenu = (contenu or "").strip()
            existant = consultation.actes.filter(type=type_acte).first()
            if not contenu:
                if existant is not None:
                    existant.delete()
                continue
            if existant is None:
                Prescription.objects.create(consultation=consultation, type=type_acte, contenu=contenu)
            elif existant.contenu != contenu:
                existant.contenu = contenu
                existant.save(update_fields=["contenu"])
