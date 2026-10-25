import datetime

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.utils import timezone

from core.forms import MESSAGE_EMAIL_UTILISE, StyledFormMixin, email_deja_utilise
from patients.models import ConstantesVitales

from .models import Infirmier, TypeSoin

User = get_user_model()

AIDE_ZONES = "Séparées par des virgules, par exemple : Ariana, La Marsa. Votre ville d'exercice est déjà comprise."
AIDE_SOINS = "Ne cochez rien si vous pratiquez tous les soins."
FORMAT_DATE_HEURE = "%Y-%m-%dT%H:%M"


def _liste_villes(texte):
    """« Ariana,  la Marsa , » → ["Ariana", "la Marsa"]."""
    return [" ".join(v.split()) for v in (texte or "").split(",") if v.strip()]


def numero_ordre_utilise(numero, exclure_pk=None):
    infirmiers = Infirmier.objects.filter(numero_ordre__iexact=numero)
    if exclure_pk is not None:
        infirmiers = infirmiers.exclude(pk=exclure_pk)
    return infirmiers.exists()


class ChampSoins(forms.MultipleChoiceField):
    def __init__(self, **kwargs):
        super().__init__(
            label="Soins pratiqués", choices=TypeSoin.choices, required=False, help_text=AIDE_SOINS,
            widget=forms.CheckboxSelectMultiple(attrs={"class": "sr-only"}), **kwargs,
        )


class ChampDateHeure(forms.DateTimeField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Passage prévu")
        super().__init__(
            input_formats=[FORMAT_DATE_HEURE],
            widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=FORMAT_DATE_HEURE), **kwargs,
        )


class InscriptionInfirmierForm(StyledFormMixin, UserCreationForm):
    """Crée le compte (rôle infirmier, en attente de validation) et le profil professionnel en une seule fois."""

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    email = forms.EmailField(label="Adresse e-mail")

    telephone = forms.CharField(label="Téléphone", max_length=20)
    numero_ordre = forms.CharField(label="Numéro d'inscription à l'Ordre", max_length=30)
    ville = forms.CharField(label="Ville d'exercice", max_length=100)
    zones = forms.CharField(label="Autres villes desservies", max_length=500, required=False, help_text=AIDE_ZONES)
    soins = ChampSoins()

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
            ville="address-level2", password1="new-password", password2="new-password",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_deja_utilise(email):
            raise forms.ValidationError(MESSAGE_EMAIL_UTILISE)
        return email

    def clean_numero_ordre(self):
        numero = self.cleaned_data["numero_ordre"].strip().upper()
        if numero_ordre_utilise(numero):
            raise forms.ValidationError("Ce numéro d'Ordre est déjà enregistré.")
        return numero

    def clean_zones(self):
        return _liste_villes(self.cleaned_data.get("zones"))

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.INFIRMIER
        user.est_valide = False  # un administrateur vérifie le numéro d'Ordre avant
        user.save()
        infirmier = Infirmier(
            user=user,
            telephone=self.cleaned_data["telephone"],
            numero_ordre=self.cleaned_data["numero_ordre"],
            ville=self.cleaned_data["ville"],
            zones=self.cleaned_data["zones"],
            soins=self.cleaned_data["soins"],
        )
        infirmier.clean()
        infirmier.save()
        return user


class ProfilInfirmierForm(StyledFormMixin, forms.ModelForm):
    """Profil professionnel et identité (prénom, nom, e-mail du compte) sur la même page."""

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    email = forms.EmailField(label="Adresse e-mail")
    zones = forms.CharField(label="Autres villes desservies", max_length=500, required=False, help_text=AIDE_ZONES)
    soins = ChampSoins()

    class Meta:
        model = Infirmier
        fields = ("telephone", "ville", "zones", "soins", "disponible")
        labels = {"telephone": "Téléphone", "ville": "Ville d'exercice", "disponible": "Disponible pour de nouvelles demandes"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.initial.update(
            first_name=user.first_name, last_name=user.last_name, email=user.email,
            zones=", ".join(self.instance.zones),
        )
        self._style_fields()
        self._autocompleter(first_name="given-name", last_name="family-name", email="email", telephone="tel", ville="address-level2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if email_deja_utilise(email, exclure_pk=self.instance.user.pk):
            raise forms.ValidationError(MESSAGE_EMAIL_UTILISE)
        return email

    def clean_zones(self):
        return _liste_villes(self.cleaned_data.get("zones"))

    @transaction.atomic
    def save(self, commit=True):
        infirmier = super().save(commit=False)
        user = infirmier.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            infirmier.save()
        return infirmier


class PassageForm(StyledFormMixin, forms.Form):
    """Date et heure du passage : pour accepter une demande ou la replanifier."""

    date_prevue = ChampDateHeure()

    def __init__(self, *args, intervention=None, **kwargs):
        super().__init__(*args, **kwargs)
        if intervention is not None and not self.is_bound:
            if intervention.date_prevue:
                self.initial["date_prevue"] = timezone.localtime(intervention.date_prevue)
            else:
                heure, minute = intervention.heure_conseillee
                jour = max(intervention.date_souhaitee, timezone.localdate())
                self.initial["date_prevue"] = datetime.datetime.combine(jour, datetime.time(heure, minute))
        self._style_fields()

    def clean_date_prevue(self):
        date = self.cleaned_data["date_prevue"]
        if date < timezone.now():
            raise forms.ValidationError("Le passage prévu ne peut pas être dans le passé.")
        return date


class CompteRenduForm(StyledFormMixin, forms.Form):
    """Compte rendu de soin et constantes relevées (toutes facultatives)."""

    compte_rendu = forms.CharField(
        label="Compte rendu", widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Soin réalisé, tolérance, observations, conseils donnés au patient.",
    )
    realisee_le = ChampDateHeure(label="Soin réalisé le")
    temperature = forms.DecimalField(label="Température (°C)", required=False, min_value=30, max_value=45, max_digits=4, decimal_places=1)
    tension_systolique = forms.IntegerField(label="Tension : systolique (mmHg)", required=False, min_value=50, max_value=260)
    tension_diastolique = forms.IntegerField(label="Tension : diastolique (mmHg)", required=False, min_value=30, max_value=160)
    frequence_cardiaque = forms.IntegerField(label="Pouls (battements/min)", required=False, min_value=20, max_value=250)
    saturation_oxygene = forms.IntegerField(label="Saturation en oxygène (%)", required=False, min_value=50, max_value=100)

    CONSTANTES = ("temperature", "tension_systolique", "tension_diastolique", "frequence_cardiaque", "saturation_oxygene")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("realisee_le", timezone.localtime().replace(second=0, microsecond=0))
        self._style_fields()

    def clean_realisee_le(self):
        date = self.cleaned_data["realisee_le"]
        if date > timezone.now():
            raise forms.ValidationError("Le soin ne peut pas être réalisé dans le futur.")
        return date

    def clean(self):
        donnees = super().clean()
        haute, basse = donnees.get("tension_systolique"), donnees.get("tension_diastolique")
        if (haute is None) != (basse is None):
            self.add_error("tension_diastolique" if basse is None else "tension_systolique", "Indiquez les deux chiffres de la tension.")
        elif haute is not None and basse >= haute:
            self.add_error("tension_diastolique", "Le second chiffre doit être plus petit que le premier.")
        return donnees

    def constantes(self):
        """None si aucune constante n'a été saisie."""
        valeurs = {nom: self.cleaned_data.get(nom) for nom in self.CONSTANTES}
        if all(v is None for v in valeurs.values()):
            return None
        return ConstantesVitales(**valeurs)


class AnnulationForm(StyledFormMixin, forms.Form):
    motif = forms.CharField(
        label="Motif de l'annulation", max_length=200,
        help_text="Ex. patient absent, soin déjà fait à l'hôpital, prescription arrêtée.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
