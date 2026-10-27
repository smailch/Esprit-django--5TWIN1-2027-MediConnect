from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'core'

    def ready(self):
        from . import signaux

        # Après le dernier « migrate » : toutes les permissions existent, on peut remplir les groupes des rôles.
        post_migrate.connect(signaux.apres_migration, dispatch_uid="core_groupes_des_roles")
