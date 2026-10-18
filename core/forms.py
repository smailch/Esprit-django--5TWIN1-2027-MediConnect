from django import forms
from django.contrib.auth.forms import AuthenticationForm

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


class ConnexionForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Identifiant"
        self.fields["password"].label = "Mot de passe"
        self._style_fields()
