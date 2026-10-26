"""Signaux de core : journal des connexions, blocage après échecs, groupes des rôles."""
import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from . import roles, securite
from .models import JournalConnexion, User

journal = logging.getLogger("mediconnect.securite")
E = JournalConnexion.Evenement


@receiver(user_logged_in, dispatch_uid="core_connexion")
def connexion(sender, request, user, **kwargs):
    securite.effacer(user.username)
    securite.consigner(E.CONNEXION, request, user)


@receiver(user_login_failed, dispatch_uid="core_echec")
def echec(sender, credentials, request=None, **kwargs):
    identifiant = credentials.get("username", "")
    securite.consigner(E.ECHEC, request, identifiant=identifiant)
    if securite.noter_echec(identifiant, securite.adresse_ip(request)):
        securite.consigner(E.BLOCAGE, request, identifiant=identifiant)


@receiver(user_logged_out, dispatch_uid="core_deconnexion")
def deconnexion(sender, request, user, **kwargs):
    if user is not None:
        securite.consigner(E.DECONNEXION, request, user)


@receiver(post_save, sender=User, dispatch_uid="core_ranger_dans_son_groupe")
def ranger_dans_son_groupe(sender, instance, raw=False, **kwargs):
    if raw:  # chargement de données (loaddata)
        return
    try:
        roles.ranger(instance)
    except Exception:  # le groupe sera corrigé au prochain « migrate » : l'enregistrement du compte passe avant
        journal.exception("Groupe du rôle non mis à jour pour %s", instance.username)


def apres_migration(sender, **kwargs):
    """post_migrate est envoyé pour chaque app qui a des modèles, dans l'ordre d'INSTALLED_APPS, et les permissions
    d'une app sont créées à son tour : on attend la dernière pour que toutes les permissions existent."""
    from django.apps import apps

    if sender.label != [a for a in apps.get_app_configs() if a.models_module is not None][-1].label:
        return
    bilan = roles.synchroniser_groupes()
    comptes = roles.ranger_tous()
    if kwargs.get("verbosity", 1) >= 1:
        print(f"  Groupes des rôles à jour ({', '.join(f'{n} : {p} permissions' for n, p in bilan.items())}) ; {comptes} compte(s) rangé(s).")
