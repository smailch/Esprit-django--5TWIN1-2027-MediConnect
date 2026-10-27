from django.apps import AppConfig


class IaConfig(AppConfig):
    default_auto_field = "django_mongodb_backend.fields.ObjectIdAutoField"
    name = "ia"
    verbose_name = "Intelligence artificielle"
