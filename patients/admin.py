from django.contrib import admin

from .models import Allergie, DossierMedical, Mesure, Patient, Symptome, Triage


class DossierMedicalInline(admin.StackedInline):
    """Dossier médical édité sur la même page que le patient."""

    model = DossierMedical
    extra = 1
    max_num = 1
    can_delete = False
    verbose_name = "dossier médical"
    verbose_name_plural = "dossier médical"


class AllergieInline(admin.TabularInline):
    """Allergies éditées sur la même page que le patient."""

    model = Allergie
    extra = 0
    fields = ("substance", "type", "gravite", "reaction", "active")


class MesureInline(admin.TabularInline):
    """Mesures de santé éditées sur la même page que le patient."""

    model = Mesure
    extra = 0
    fields = ("type", "valeur", "mesure_le", "note")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("__str__", "ville", "telephone", "sexe", "cree_le")
    list_select_related = ("user",)
    list_filter = ("sexe", "cree_le")
    search_fields = (
        "user__last_name",
        "user__first_name",
        "user__username",
        "user__email",
        "telephone",
        "ville",
    )
    autocomplete_fields = ("user",)
    inlines = [DossierMedicalInline, AllergieInline, MesureInline]


@admin.register(DossierMedical)
class DossierMedicalAdmin(admin.ModelAdmin):
    list_display = ("patient", "groupe_sanguin", "modifie_le")
    list_select_related = ("patient__user",)
    list_filter = ("groupe_sanguin",)
    search_fields = ("patient__user__last_name", "patient__user__first_name")
    autocomplete_fields = ("patient",)


@admin.register(Allergie)
class AllergieAdmin(admin.ModelAdmin):
    list_display = ("substance", "patient", "type", "gravite", "active", "decouverte_le")
    list_select_related = ("patient__user",)
    list_filter = ("gravite", "type", "active")
    search_fields = ("substance", "patient__user__last_name", "patient__user__first_name")
    autocomplete_fields = ("patient",)


@admin.register(Symptome)
class SymptomeAdmin(admin.ModelAdmin):
    list_display = ("nom", "poids", "drapeau_rouge", "niveau_minimal", "actif")
    list_editable = ("poids", "actif")  # gestion rapide des pondérations
    list_filter = ("drapeau_rouge", "niveau_minimal", "actif")
    search_fields = ("nom",)


@admin.register(Triage)
class TriageAdmin(admin.ModelAdmin):
    """Le triage est un dossier médical calculé par le système : en lecture
    seule, sauf le statut et le niveau requalifié par le médecin."""

    CHAMPS_MODIFIABLES = ("statut", "niveau_medecin")

    list_display = (
        "patient",
        "medecin_nom",
        "niveau",
        "niveau_medecin",
        "score",
        "statut",
        "cree_le",
    )
    list_select_related = ("patient__user",)
    list_filter = ("statut", "niveau", "niveau_medecin", "cree_le")
    search_fields = (
        "patient__user__last_name",
        "patient__user__first_name",
        "medecin_nom",
    )

    fields = (
        "patient",
        "medecin_nom",
        "medecin_specialite",
        "cree_le",
        "statut",
        "niveau_medecin",
        "niveau",
        "score",
        "explication",
        "drapeaux_rouges",
        "symptomes_declares",
        "auto_evaluation_declaree",
        "constantes_declarees",
        "texte_libre",
    )
    readonly_fields = (
        "patient",
        "medecin_nom",
        "medecin_specialite",
        "cree_le",
        "niveau",
        "score",
        "explication",
        "drapeaux_rouges",
        "symptomes_declares",
        "auto_evaluation_declaree",
        "constantes_declarees",
        "texte_libre",
    )

    def has_add_permission(self, request):
        # Un triage est créé par le patient via le site, jamais à la main.
        return False

    @admin.display(description="Symptômes déclarés")
    def symptomes_declares(self, obj):
        noms = [
            s.nom + (" (alerte)" if s.drapeau_rouge else "")
            for s in (obj.symptomes or [])
        ]
        return ", ".join(noms) or "—"

    @admin.display(description="Auto-évaluation du patient")
    def auto_evaluation_declaree(self, obj):
        resume = obj.auto_evaluation_resume()
        return ", ".join(f"{e['nom']} : {e['libelle'].lower()} ({e['valeur']}/5)" for e in resume) or "—"

    @admin.display(description="Constantes déclarées")
    def constantes_declarees(self, obj):
        c = obj.constantes
        if not c:
            return "—"
        morceaux = []
        if c.temperature is not None:
            morceaux.append(f"température {c.temperature} °C")
        if c.tension_systolique is not None or c.tension_diastolique is not None:
            morceaux.append(
                f"tension {c.tension_systolique or '?'}/{c.tension_diastolique or '?'}"
            )
        if c.frequence_cardiaque is not None:
            morceaux.append(f"pouls {c.frequence_cardiaque}/min")
        if c.saturation_oxygene is not None:
            morceaux.append(f"saturation {c.saturation_oxygene} %")
        return ", ".join(morceaux) or "—"


@admin.register(Mesure)
class MesureAdmin(admin.ModelAdmin):
    list_display = ("patient", "type", "valeur", "mesure_le")
    list_select_related = ("patient__user",)
    list_filter = ("type", "mesure_le")
    search_fields = ("patient__user__last_name", "patient__user__first_name")
    autocomplete_fields = ("patient",)
