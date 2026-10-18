from django.apps import AppConfig


class PharmaciesConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'pharmacies'
