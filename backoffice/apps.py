from django.apps import AppConfig


class BackofficeConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'backoffice'
