from django.contrib import admin

from .models import Infirmier, InterventionDomicile


class InterventionInline(admin.TabularInline):
    """Interventions de l'infirmier, en lecture sur sa fiche."""

    model = InterventionDomicile
    extra = 0
    fields = ("patient", "type_soin", "ville", "date_prevue", "statut")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Infirmier)
class InfirmierAdmin(admin.ModelAdmin):
    list_display = ("__str__", "numero_ordre", "ville", "telephone", "disponible", "compte_valide", "cree_le")
    list_select_related = ("user",)
    list_filter = ("disponible", "user__est_valide", "ville")
    search_fields = (
        "user__last_name",
        "user__first_name",
        "user__username",
        "user__email",
        "numero_ordre",
        "telephone",
        "ville",
    )
    autocomplete_fields = ("user",)
    inlines = [InterventionInline]
    actions = ["valider_comptes", "retirer_validation"]

    @admin.display(boolean=True, description="Compte validé")
    def compte_valide(self, obj):
        return obj.user.est_valide

    def _valider(self, request, queryset, valeur):
        # Une requête par compte : MongoDB ne met pas à jour une collection en filtrant sur une autre.
        nombre = 0
        for infirmier in queryset.select_related("user"):
            if infirmier.user.est_valide != valeur:
                infirmier.user.est_valide = valeur
                infirmier.user.save(update_fields=["est_valide"])
                nombre += 1
        return nombre

    @admin.action(description="Valider les comptes sélectionnés (numéro d'Ordre vérifié)")
    def valider_comptes(self, request, queryset):
        self.message_user(request, f"{self._valider(request, queryset, True)} compte(s) validé(s).")

    @admin.action(description="Retirer la validation des comptes sélectionnés")
    def retirer_validation(self, request, queryset):
        self.message_user(request, f"Validation retirée pour {self._valider(request, queryset, False)} compte(s).")


@admin.register(InterventionDomicile)
class InterventionDomicileAdmin(admin.ModelAdmin):
    list_display = ("__str__", "infirmier", "ville", "date_souhaitee", "date_prevue", "statut", "niveau_alerte", "cree_le")
    list_select_related = ("patient__user", "infirmier__user")
    list_filter = ("statut", "niveau_alerte", "type_soin", "moment", "date_souhaitee")
    search_fields = (
        "patient__user__last_name",
        "patient__user__first_name",
        "infirmier__user__last_name",
        "infirmier__user__first_name",
        "ville",
    )
    autocomplete_fields = ("patient", "infirmier")
    readonly_fields = ("acceptee_le", "annulee_le", "cree_le", "modifie_le")
    date_hierarchy = "date_souhaitee"
    fieldsets = (
        ("Demande", {"fields": ("patient", "consultation", "type_soin", "description", "adresse", "ville", "date_souhaitee", "moment")}),
        ("Prise en charge", {"fields": ("statut", "infirmier", "date_prevue", "acceptee_le")}),
        ("Compte rendu", {"fields": ("realisee_le", "compte_rendu", "constantes")}),
        ("Alertes du compte rendu", {"fields": ("niveau_alerte", "signes_alerte", "analyse_ia")}),
        ("Annulation", {"fields": ("annulee_le", "motif_annulation")}),
        ("Suivi", {"fields": ("cree_le", "modifie_le")}),
    )
