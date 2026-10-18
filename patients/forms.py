from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction

from .models import DossierMedical, Patient, Symptome

User = get_user_model()

INPUT_CLASSES = (
    "block w-full rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-sm "
    "text-[#1F2937] placeholder:text-gray-400 focus:border-primary "
    "focus:outline-none focus:ring-2 focus:ring-primary/30"
)


class StyledFormMixin:
    """Applique le même style Tailwind à tous les champs."""

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                continue
            widget.attrs["class"] = INPUT_CLASSES
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)


class ConnexionForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Identifiant"
        self.fields["password"].label = "Mot de passe"
        self._style_fields()


class InscriptionPatientForm(StyledFormMixin, UserCreationForm):
    """Crée le compte, le patient et son dossier médical en une seule fois."""

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    email = forms.EmailField(label="Adresse e-mail")

    date_naissance = forms.DateField(
        label="Date de naissance",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    sexe = forms.ChoiceField(label="Sexe", choices=Patient.Sexe.choices)
    telephone = forms.CharField(label="Téléphone", max_length=20)
    ville = forms.CharField(label="Ville", max_length=100)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {"username": "Identifiant"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Mot de passe"
        self.fields["password2"].label = "Confirmation du mot de passe"
        self._style_fields()

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.PATIENT
        user.save()
        patient = Patient.objects.create(
            user=user,
            date_naissance=self.cleaned_data["date_naissance"],
            sexe=self.cleaned_data["sexe"],
            telephone=self.cleaned_data["telephone"],
            ville=self.cleaned_data["ville"],
        )
        DossierMedical.objects.create(patient=patient)
        return user


class ProfilPatientForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Patient
        fields = (
            "date_naissance",
            "sexe",
            "telephone",
            "adresse",
            "ville",
            "contact_urgence_nom",
            "contact_urgence_tel",
        )
        labels = {
            "date_naissance": "Date de naissance",
            "sexe": "Sexe",
            "telephone": "Téléphone",
            "adresse": "Adresse",
            "ville": "Ville",
            "contact_urgence_nom": "Contact d'urgence (nom)",
            "contact_urgence_tel": "Contact d'urgence (téléphone)",
        }
        widgets = {"date_naissance": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class DossierMedicalForm(StyledFormMixin, forms.ModelForm):
    allergies = forms.CharField(
        label="Allergies",
        required=False,
        help_text="Séparées par des virgules (ex. pénicilline, arachide).",
    )

    class Meta:
        model = DossierMedical
        fields = ("groupe_sanguin", "allergies", "antecedents", "traitements_en_cours")
        labels = {
            "groupe_sanguin": "Groupe sanguin",
            "antecedents": "Antécédents médicaux",
            "traitements_en_cours": "Traitements en cours",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["allergies"] = ", ".join(self.instance.allergies or [])
        self._style_fields()

    def clean_allergies(self):
        brut = self.cleaned_data.get("allergies", "")
        return [a.strip() for a in brut.split(",") if a.strip()]


class SymptomesForm(StyledFormMixin, forms.Form):
    """Déclaration des symptômes et des constantes pour un triage."""

    symptomes = forms.ModelMultipleChoiceField(
        label="Symptômes",
        queryset=Symptome.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    temperature = forms.DecimalField(
        label="Température (°C)", required=False, min_value=30, max_value=45,
        max_digits=4, decimal_places=1,
    )
    tension_systolique = forms.IntegerField(
        label="Tension systolique (mmHg)", required=False, min_value=40, max_value=300
    )
    frequence_cardiaque = forms.IntegerField(
        label="Fréquence cardiaque (battements/min)", required=False, min_value=20, max_value=250
    )
    saturation_oxygene = forms.IntegerField(
        label="Saturation en oxygène (%)", required=False, min_value=50, max_value=100
    )
    texte_libre = forms.CharField(
        label="Décrivez ce que vous ressentez",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        max_length=2000,
    )

    CONSTANTES = (
        "temperature", "tension_systolique", "frequence_cardiaque", "saturation_oxygene",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["symptomes"].queryset = Symptome.objects.filter(actif=True).order_by("nom")
        self._style_fields()

    def clean(self):
        data = super().clean()
        if not data.get("symptomes") and not (data.get("texte_libre") or "").strip():
            raise forms.ValidationError(
                "Cochez au moins un symptôme ou décrivez ce que vous ressentez."
            )
        return data

    def constantes(self):
        return {
            k: self.cleaned_data[k]
            for k in self.CONSTANTES
            if self.cleaned_data.get(k) is not None
        }
