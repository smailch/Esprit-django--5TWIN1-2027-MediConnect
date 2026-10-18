from django.contrib import admin

from .models import DossierMedical, Patient, Symptome, Triage


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("__str__", "ville", "telephone", "sexe", "cree_le")
    search_fields = ("user__last_name", "user__first_name", "telephone", "ville")


@admin.register(DossierMedical)
class DossierMedicalAdmin(admin.ModelAdmin):
    list_display = ("patient", "groupe_sanguin", "modifie_le")


@admin.register(Symptome)
class SymptomeAdmin(admin.ModelAdmin):
    list_display = ("nom", "poids", "drapeau_rouge", "niveau_minimal", "actif")
    list_filter = ("drapeau_rouge", "actif")
    search_fields = ("nom",)


@admin.register(Triage)
class TriageAdmin(admin.ModelAdmin):
    list_display = ("patient", "niveau", "niveau_medecin", "score", "statut", "cree_le")
    list_filter = ("statut", "niveau")
