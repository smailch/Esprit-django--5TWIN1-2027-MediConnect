from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import User


# Avec un modèle d'utilisateur personnalisé, les formulaires de l'admin doivent
# désigner explicitement ce modèle.
class CoreUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User


class CoreUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = CoreUserChangeForm
    add_form = CoreUserCreationForm

    list_display = ("username", "email", "role", "est_valide", "is_staff", "is_active")
    list_filter = ("role", "est_valide", "is_staff", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("MediConnect", {"fields": ("role", "est_valide")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("MediConnect", {"fields": ("role", "est_valide")}),
    )

    actions = ["valider_comptes", "retirer_validation"]

    @admin.action(description="Valider les comptes sélectionnés")
    def valider_comptes(self, request, queryset):
        nombre = queryset.update(est_valide=True)
        self.message_user(request, f"{nombre} compte(s) validé(s).")

    @admin.action(description="Retirer la validation des comptes sélectionnés")
    def retirer_validation(self, request, queryset):
        nombre = queryset.update(est_valide=False)
        self.message_user(request, f"Validation retirée pour {nombre} compte(s).")
