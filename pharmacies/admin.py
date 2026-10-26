from django.contrib import admin

from .models import Ordonnance, Pharmacie


@admin.register(Pharmacie)
class PharmacieAdmin(admin.ModelAdmin):
    list_display = ("nom", "ville", "telephone", "de_garde", "user")
    list_select_related = ("user",)
    list_filter = ("ville", "de_garde")
    search_fields = ("nom", "ville", "user__username")
    autocomplete_fields = ("user",)


@admin.register(Ordonnance)
class OrdonnanceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "prescripteur_nom", "pharmacie", "statut", "date_emission", "valide_jusqu_au")
    list_select_related = ("patient__user", "pharmacie")
    list_filter = ("statut", "date_emission")
    search_fields = ("patient__user__last_name", "patient__user__first_name", "prescripteur_nom", "medicaments")
    autocomplete_fields = ("patient", "pharmacie")
    raw_id_fields = ("consultation",)
    readonly_fields = ("delivree_le", "cree_le", "modifie_le")
