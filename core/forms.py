from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm

INPUT_CLASSES = "field"  # style « verre » défini dans static/css/ui.css


class StyledFormMixin:
    """Applique le style commun à tous les champs d'un formulaire.

    Partagé par toutes les apps : `from core.forms import StyledFormMixin`.
    """

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            widget.attrs["class"] = INPUT_CLASSES
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)

    def _autocompleter(self, **valeurs):
        """Indique au navigateur et aux lecteurs d'écran le sens de chaque champ (autocomplete : « email », « tel »…)."""
        for nom, valeur in valeurs.items():
            if nom in self.fields:
                self.fields[nom].widget.attrs["autocomplete"] = valeur


class ConnexionForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Identifiant"
        self.fields["password"].label = "Mot de passe"
        self._style_fields()
        self._autocompleter(username="username", password="current-password")


def email_deja_utilise(email, exclure_pk=None):
    """Un autre compte utilise-t-il déjà cette adresse (majuscules ignorées) ?"""
    comptes = get_user_model().objects.filter(email__iexact=(email or "").strip())
    if exclure_pk is not None:
        comptes = comptes.exclude(pk=exclure_pk)
    return comptes.exists()


MESSAGE_EMAIL_UTILISE = "Un compte existe déjà avec cette adresse e-mail."


class ChangementMotDePasseForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Mot de passe actuel"
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password2"].label = "Confirmation du nouveau mot de passe"
        self._style_fields()
        self._autocompleter(old_password="current-password", new_password1="new-password", new_password2="new-password")


class DemandeReinitialisationForm(StyledFormMixin, PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "Adresse e-mail de votre compte"
        self._style_fields()
        self._autocompleter(email="email")


class NouveauMotDePasseForm(StyledFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password2"].label = "Confirmation du nouveau mot de passe"
        self._style_fields()
        self._autocompleter(new_password1="new-password", new_password2="new-password")
