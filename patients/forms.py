from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction

from core.forms import MESSAGE_EMAIL_UTILISE, StyledFormMixin, email_deja_utilise

from .echelles import ECHELLES, NIVEAU_MAX, choix
from .models import Allergie, DossierMedical, Mesure, Patient, Symptome

User = get_user_model()


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
        self._autocompleter(
            username="username", first_name="given-name", last_name="family-name", email="email", telephone="tel",
            date_naissance="bday", password1="new-password", password2="new-password",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_deja_utilise(email):
            raise forms.ValidationError(MESSAGE_EMAIL_UTILISE)
        return email

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
        self._autocompleter(date_naissance="bday", telephone="tel", adresse="street-address", ville="address-level2")


class DossierMedicalForm(StyledFormMixin, forms.ModelForm):
    """Les allergies ne sont plus saisies ici : elles ont leur propre page (modèle Allergie)."""

    class Meta:
        model = DossierMedical
        fields = ("groupe_sanguin", "antecedents", "traitements_en_cours")
        labels = {
            "groupe_sanguin": "Groupe sanguin",
            "antecedents": "Antécédents médicaux",
            "traitements_en_cours": "Traitements en cours",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


def _champ_echelle(nom):
    return forms.TypedChoiceField(
        label=ECHELLES[nom]["question"],
        choices=choix(nom),
        coerce=int,
        empty_value=0,
        initial=0,
        required=False,
        widget=forms.RadioSelect(attrs={"class": "sr-only"}),
    )


class AutoEvaluationForm(forms.Form):
    """Ce que le patient ressent, sur des échelles de 0 à 5 en mots simples."""

    douleur = _champ_echelle("douleur")
    fievre = _champ_echelle("fievre")
    respiration = _champ_echelle("respiration")
    etat_general = _champ_echelle("etat_general")

    def echelles(self):
        """Champs d'échelle, dans l'ordre d'affichage."""
        return [self[nom] for nom in ECHELLES]

    def auto_evaluation(self):
        return {nom: self.cleaned_data.get(nom) or 0 for nom in ECHELLES}


class OrientationForm(StyledFormMixin, forms.Form):
    """« Quel médecin consulter ? » : un texte libre, rien n'est enregistré."""

    texte = forms.CharField(
        label="Décrivez ce que vous ressentez",
        min_length=3,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
        error_messages={"required": "Décrivez en quelques mots ce que vous ressentez.", "min_length": "Décrivez en quelques mots ce que vous ressentez."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class SymptomesForm(StyledFormMixin, AutoEvaluationForm):
    """Déclaration des symptômes d'un patient : cases à cocher, échelles de 0 à 5,
    température facultative et texte libre."""

    symptomes = forms.ModelMultipleChoiceField(
        label="Symptômes",
        queryset=Symptome.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "sr-only"}),
    )
    temperature = forms.DecimalField(
        label="Température mesurée (facultatif)",
        required=False,
        min_value=30,
        max_value=45,
        max_digits=4,
        decimal_places=1,
        help_text="Si vous avez pris votre température, indiquez-la : elle remplace l'échelle de fièvre.",
    )
    texte_libre = forms.CharField(
        label="Décrivez ce que vous ressentez",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        max_length=2000,
    )

    CONSTANTES = ("temperature",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["symptomes"].queryset = Symptome.objects.filter(actif=True).order_by("nom")
        self._style_fields()

    def clean(self):
        data = super().clean()
        if (
            not data.get("symptomes")
            and not (data.get("texte_libre") or "").strip()
            and not any(data.get(nom) for nom in ECHELLES)
        ):
            raise forms.ValidationError(
                "Cochez un symptôme, indiquez ce que vous ressentez sur les échelles "
                "ou décrivez-le avec vos mots."
            )
        return data

    def constantes(self):
        return {
            k: self.cleaned_data[k]
            for k in self.CONSTANTES
            if self.cleaned_data.get(k) is not None
        }


class AllergieForm(StyledFormMixin, forms.ModelForm):
    """Ajout et modification d'une allergie. Le patient est imposé par la vue (jamais saisi)."""

    class Meta:
        model = Allergie
        fields = ("substance", "type", "gravite", "reaction", "decouverte_le", "active")
        labels = {
            "substance": "Allergique à",
            "type": "Type d'allergie",
            "gravite": "Gravité",
            "reaction": "Réaction",
            "decouverte_le": "Date de la première réaction",
            "active": "Cette allergie est toujours d'actualité",
        }
        widgets = {
            "gravite": forms.RadioSelect(attrs={"class": "sr-only"}),
            "decouverte_le": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, patient, **kwargs):
        super().__init__(*args, **kwargs)
        # Imposé ici pour que les règles du modèle (doublon, date de naissance) s'appliquent.
        self.instance.patient = patient
        self._style_fields()


class MesureForm(StyledFormMixin, forms.ModelForm):
    """Ajout et modification d'une mesure de santé. Le patient est imposé par la vue (jamais saisi)."""

    class Meta:
        model = Mesure
        fields = ("type", "valeur", "valeur2", "mesure_le", "note")
        labels = {
            "type": "Type de mesure",
            "valeur": "Valeur (tension : le premier chiffre)",
            "valeur2": "Second chiffre de la tension",
            "mesure_le": "Date et heure de la mesure",
            "note": "Remarque (facultatif)",
        }
        widgets = {
            "valeur": forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
            "valeur2": forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
            "mesure_le": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, patient, **kwargs):
        super().__init__(*args, **kwargs)
        # Imposé ici pour que les règles du modèle (doublon) s'appliquent.
        self.instance.patient = patient
        self.fields["mesure_le"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        self._style_fields()


class CompteForm(StyledFormMixin, forms.ModelForm):
    """Identité du compte : prénom, nom et adresse e-mail (l'e-mail sert aussi à réinitialiser le mot de passe)."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Prénom", "last_name": "Nom", "email": "Adresse e-mail"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for champ in self.fields.values():
            champ.required = True
        self._style_fields()
        self._autocompleter(first_name="given-name", last_name="family-name", email="email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_deja_utilise(email, exclure_pk=self.instance.pk):
            raise forms.ValidationError(MESSAGE_EMAIL_UTILISE)
        return email


class FermetureCompteForm(StyledFormMixin, forms.Form):
    """Désactiver son compte : on redemande le mot de passe, pour qu'une session laissée ouverte ne suffise pas."""

    mot_de_passe = forms.CharField(label="Votre mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._style_fields()
        self._autocompleter(mot_de_passe="current-password")

    def clean_mot_de_passe(self):
        mot_de_passe = self.cleaned_data["mot_de_passe"]
        if not self.user.check_password(mot_de_passe):
            raise forms.ValidationError("Mot de passe incorrect.")
        return mot_de_passe


class SuppressionCompteForm(FermetureCompteForm):
    """Supprimer définitivement : mot de passe, et le mot SUPPRIMER tapé en toutes lettres."""

    MOT = "SUPPRIMER"

    confirmation = forms.CharField(label="Pour confirmer, tapez SUPPRIMER")

    def clean_confirmation(self):
        confirmation = self.cleaned_data["confirmation"].strip()
        if confirmation != self.MOT:
            raise forms.ValidationError(f"Tapez exactement « {self.MOT} » pour confirmer.")
        return confirmation
