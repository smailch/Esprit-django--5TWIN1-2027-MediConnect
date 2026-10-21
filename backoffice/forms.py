from django import forms

from patients import medecins_test
from patients.models import Triage

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
    medecin = forms.ChoiceField(
        label="Médecin",
        required=False,
        choices=[("", "Tous")] + [(m["id"], m["nom"]) for m in medecins_test.tous()],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
