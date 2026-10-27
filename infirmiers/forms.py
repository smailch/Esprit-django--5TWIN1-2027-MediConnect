import datetime
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.utils import timezone

from core.forms import MESSAGE_EMAIL_UTILISE, StyledFormMixin, email_deja_utilise
from patients.models import ConstantesVitales, Consultation

from .models import Infirmier, InterventionDomicile, TypeSoin

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


REPETITIONS = (
    ("", "Une seule fois"),
    ("1", "Chaque jour"),
    ("2", "Tous les deux jours"),
    ("7", "Chaque semaine"),
)
PASSAGES_MAX = 30


class DemandeSoinForm(StyledFormMixin, forms.ModelForm):
    """Demande de soin à domicile faite par le patient (création, ou modification tant qu'elle n'est pas acceptée).

    À la création, le patient peut demander une série (« chaque jour pendant 10 jours ») : un passage par date,
    reliés par le même identifiant de série. La modification porte toujours sur un seul passage."""

    repetition = forms.ChoiceField(label="Répéter le soin", choices=REPETITIONS, required=False)
    nombre_passages = forms.IntegerField(
        label="Nombre de passages", min_value=2, max_value=PASSAGES_MAX, required=False,
        help_text=f"De 2 à {PASSAGES_MAX} passages, à partir de la date souhaitée.",
    )

    class Meta:
        model = InterventionDomicile
        fields = ("type_soin", "description", "consultation", "date_souhaitee", "moment", "adresse", "ville")
        labels = {
            "type_soin": "Soin demandé",
            "description": "Précisions pour l'infirmier",
            "consultation": "Prescrit lors de la consultation",
            "date_souhaitee": "Date souhaitée",
            "moment": "Moment de la journée",
            "adresse": "Adresse du soin",
            "ville": "Ville",
        }
        help_texts = {
            "description": "Ex. injection d'anticoagulant chaque matin, pansement de la jambe gauche, ordonnance à disposition.",
            "consultation": "Facultatif : la consultation où le médecin a prescrit ce soin.",
            "ville": "Les infirmiers qui se déplacent dans cette ville recevront votre demande.",
        }
        widgets = {"date_souhaitee": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, patient, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.patient = patient
        consultation = self.fields["consultation"]
        consultation.queryset = Consultation.objects.filter(patient=patient)
        consultation.empty_label = "Aucune"
        if self.instance._state.adding and not self.is_bound:
            self.initial.setdefault("adresse", patient.adresse)
            self.initial.setdefault("ville", patient.ville)
        self.fields["date_souhaitee"].widget.attrs["min"] = timezone.localdate().isoformat()
        if not self.instance._state.adding:  # une série ne se crée qu'à la demande
            del self.fields["repetition"], self.fields["nombre_passages"]
        self.series = []
        self._style_fields()
        self._autocompleter(adresse="street-address", ville="address-level2")

    def clean(self):
        donnees = super().clean()
        if donnees.get("repetition") and not donnees.get("nombre_passages"):
            self.add_error("nombre_passages", "Indiquez combien de passages sont prévus.")
        return donnees

    def dates_de_la_serie(self):
        """Dates des passages demandés (une seule sans répétition)."""
        debut = self.cleaned_data["date_souhaitee"]
        ecart = int(self.cleaned_data.get("repetition") or 0)
        if not ecart:
            return [debut]
        return [debut + datetime.timedelta(days=ecart * i) for i in range(self.cleaned_data["nombre_passages"])]

    def save(self, commit=True):
        """Enregistre le premier passage et, pour une série, les suivants. `self.series` : tous les passages."""
        dates = self.dates_de_la_serie() if "repetition" in self.fields else [None]
        premier = super().save(commit=False)
        if len(dates) > 1:
            premier.serie, premier.rang_serie, premier.taille_serie = uuid.uuid4().hex, 1, len(dates)
        self.series = [premier]
        for rang, date in enumerate(dates[1:], start=2):
            suivant = InterventionDomicile(
                **{nom: getattr(premier, nom) for nom in self.Meta.fields}, patient=premier.patient,
                serie=premier.serie, rang_serie=rang, taille_serie=len(dates),
            )
            suivant.date_souhaitee = date
            self.series.append(suivant)
        if commit:
            with transaction.atomic():
                for passage in self.series:
                    passage.save()
        return premier

    def clean_date_souhaitee(self):
        date = self.cleaned_data["date_souhaitee"]
        if date < timezone.localdate():
            raise forms.ValidationError("La date souhaitée ne peut pas être dans le passé.")
        return date


class HeureSerieForm(StyledFormMixin, forms.Form):
    """Heure de passage commune à tous les passages d'une série acceptée en bloc."""

    heure = forms.TimeField(label="Heure de passage, chaque jour", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    def __init__(self, *args, premier=None, **kwargs):
        super().__init__(*args, **kwargs)
        if premier is not None and not self.is_bound:
            self.initial["heure"] = datetime.time(*premier.heure_conseillee)
        self._style_fields()
