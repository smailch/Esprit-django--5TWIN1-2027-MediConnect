from django.contrib import admin

from .models import Medecin, Prescription


@admin.register(Medecin)
class MedecinAdmin(admin.ModelAdmin):
    list_display = ("code", "specialite", "ville", "disponible", "telephone")
    list_filter = ("disponible", "specialite", "ville")
    search_fields = ("code", "specialite", "ville", "user__last_name", "user__first_name", "user__username")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("type", "consultation", "cree_le")
    list_filter = ("type",)
