from django import forms
from django.contrib.auth import get_user_model

from core.forms import StyledFormMixin

from .models import Medicament, Ordonnance, Pharmacie

User = get_user_model()


class PharmacieForm(StyledFormMixin, forms.ModelForm):
    """Fiche d'une pharmacie. L'administrateur choisit le compte ; la pharmacie, elle, ne modifie que ses coordonnées."""

    class Meta:
        model = Pharmacie
        fields = ("user", "nom", "adresse", "ville", "telephone", "horaires", "de_garde")
        labels = {
            "user": "Compte de la pharmacie",
            "nom": "Nom de la pharmacie",
            "adresse": "Adresse",
            "ville": "Ville",
            "telephone": "Téléphone",
            "horaires": "Horaires d'ouverture",
            "de_garde": "Pharmacie de garde",
        }

    def __init__(self, *args, avec_compte=True, **kwargs):
        super().__init__(*args, **kwargs)
        if avec_compte:
            # Seuls les comptes « pharmacie » sans fiche (ou celui de cette fiche) sont proposés.
            pris = Pharmacie.objects.exclude(pk=self.instance.pk).values_list("user", flat=True)
            self.fields["user"].queryset = User.objects.filter(role=User.Role.PHARMACIE).exclude(pk__in=list(pris)).order_by("username")
        else:
            del self.fields["user"]
        self._style_fields()
        self._autocompleter(nom="organization", adresse="street-address", ville="address-level2", telephone="tel")


class OrdonnanceForm(StyledFormMixin, forms.ModelForm):
    """Rédaction d'une ordonnance. Le patient, la consultation et le prescripteur sont imposés par la vue (jamais saisis) :
    impossible de rattacher l'ordonnance à un autre patient en modifiant le formulaire."""

    class Meta:
        model = Ordonnance
        fields = ("medicaments", "instructions", "date_emission", "valide_jusqu_au")
        widgets = {
            "medicaments": forms.Textarea(attrs={"rows": 6}),
            "date_emission": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "valide_jusqu_au": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class TransmissionForm(StyledFormMixin, forms.Form):
    """Le patient choisit la pharmacie qui préparera son ordonnance."""

    pharmacie = forms.ModelChoiceField(
        label="Pharmacie", queryset=Pharmacie.objects.none(), empty_label="Choisissez une pharmacie",
        help_text="Les pharmacies de garde sont signalées. La pharmacie verra vos médicaments et vos allergies.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seules les pharmacies dont le compte est actif et validé peuvent recevoir une ordonnance.
        self.fields["pharmacie"].queryset = Pharmacie.objects.filter(user__is_active=True, user__est_valide=True)
        self.fields["pharmacie"].label_from_instance = lambda p: f"{p.nom} — {p.ville}" + (" (de garde)" if p.de_garde else "")
        self._style_fields()


class RuptureForm(StyledFormMixin, forms.Form):
    """La pharmacie signale qu'un médicament de l'ordonnance manque et, si elle le décide, le remplaçant retenu."""

    medicament = forms.ChoiceField(label="Médicament en rupture")
    remplacant = forms.CharField(
        label="Remplaçant retenu (facultatif)", required=False, max_length=100,
        help_text="Choisissez une suggestion ou écrivez-le vous-même. Vérifiez le dosage et prévenez le patient.",
    )

    def __init__(self, *args, lignes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medicament"].choices = [("", "Choisissez le médicament")] + [(ligne, ligne) for ligne in lignes]
        self._style_fields()


class MedicamentForm(StyledFormMixin, forms.ModelForm):
    """Ajout et modification d'un médicament du stock. La pharmacie est imposée par la vue (jamais saisie) :
    impossible d'écrire dans le stock d'une autre officine."""

    class Meta:
        model = Medicament
        fields = ("nom", "principe_actif", "dosage", "forme", "quantite", "seuil_alerte", "prix")
        labels = {"nom": "Nom du médicament", "principe_actif": "Principe actif", "dosage": "Dosage", "forme": "Forme"}
        widgets = {
            "quantite": forms.NumberInput(attrs={"min": 0, "inputmode": "numeric"}),
            "seuil_alerte": forms.NumberInput(attrs={"min": 0, "inputmode": "numeric"}),
            "prix": forms.NumberInput(attrs={"min": 0, "step": "0.001", "inputmode": "decimal"}),
        }

    def __init__(self, *args, pharmacie, **kwargs):
        super().__init__(*args, **kwargs)
        # Imposée ici pour que la règle du modèle (pas de doublon dans le même stock) s'applique.
        self.instance.pharmacie = pharmacie
        self._style_fields()


class FiltreStockForm(forms.Form):
    """Recherche dans le stock (envoyée en GET)."""

    ETATS = (("", "Tous"), (Medicament.RUPTURE, "En rupture"), (Medicament.STOCK_BAS, "Stock bas"), (Medicament.DISPONIBLE, "Disponibles"))

    q = forms.CharField(label="Nom ou principe actif", required=False, max_length=100)
    etat = forms.ChoiceField(label="État du stock", required=False, choices=ETATS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for champ in self.fields.values():
            champ.widget.attrs["class"] = "field"


class FiltreOrdonnancesForm(forms.Form):
    """Filtre de la liste des ordonnances (envoyé en GET)."""

    statut = forms.ChoiceField(label="Statut", required=False, choices=[("", "Tous")] + list(Ordonnance.Statut.choices))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["statut"].widget.attrs["class"] = "field"


class FiltrePharmaciesForm(forms.Form):
    """Recherche dans l'annuaire des pharmacies (envoyée en GET)."""

    q = forms.CharField(label="Nom ou ville", required=False, max_length=100)
    de_garde = forms.BooleanField(label="De garde uniquement", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["q"].widget.attrs["class"] = "field"
