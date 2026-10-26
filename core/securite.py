"""Sécurité des connexions : protection contre la force brute et journal des accès.

- Après CONNEXION_ESSAIS_MAX échecs pour un même identifiant, la connexion de cet identifiant est refusée pendant
  CONNEXION_BLOCAGE_MINUTES, même avec le bon mot de passe (OWASP : « Blocking Brute Force Attacks »). Une même
  adresse IP a droit à quatre fois plus d'essais (plusieurs personnes peuvent partager une adresse, au campus).
- Le message reste le même que l'identifiant existe ou non : on ne révèle pas qui a un compte.
- Chaque connexion, échec, blocage et déconnexion est enregistré dans core.JournalConnexion (traçabilité),
  sans jamais stocker le mot de passe saisi.

Les compteurs vivent dans le cache Django : Redis en production (partagé entre les processus), mémoire en local.
"""
import logging

from django.conf import settings
from django.core.cache import cache

journal = logging.getLogger("mediconnect.securite")

FACTEUR_IP = 4


def adresse_ip(request):
    """Adresse du client. Derrière le proxy de Railway, la vraie adresse est la première de X-Forwarded-For."""
    if request is None:
        return None
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmise and getattr(settings, "PRODUCTION", False):
        return transmise.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _cle_identifiant(identifiant):
    return "connexion:id:" + (identifiant or "").strip().casefold()[:150]


def _cle_ip(ip):
    return f"connexion:ip:{ip}"


def _duree():
    return settings.CONNEXION_BLOCAGE_MINUTES * 60


def _depasse(cle, maximum):
    return (cache.get(cle) or 0) >= maximum


def est_bloque(identifiant, ip):
    """La connexion est-elle refusée pour le moment (trop d'échecs récents) ?"""
    maximum = settings.CONNEXION_ESSAIS_MAX
    return _depasse(_cle_identifiant(identifiant), maximum) or (ip is not None and _depasse(_cle_ip(ip), maximum * FACTEUR_IP))


def _incrementer(cle):
    cache.add(cle, 0, _duree())
    try:
        return cache.incr(cle)
    except ValueError:  # la clé vient d'expirer
        cache.set(cle, 1, _duree())
        return 1


def noter_echec(identifiant, ip):
    """Compte un échec ; renvoie True si cet échec déclenche le blocage."""
    deja = est_bloque(identifiant, ip)
    n = _incrementer(_cle_identifiant(identifiant))
    if ip is not None:
        _incrementer(_cle_ip(ip))
    if not deja and est_bloque(identifiant, ip):
        journal.warning("Connexion bloquée %s min après %s échecs (identifiant %r, IP %s)",
                        settings.CONNEXION_BLOCAGE_MINUTES, n, identifiant, ip)
        return True
    return False


def effacer(identifiant):
    """Connexion réussie : le compteur de l'identifiant repart de zéro."""
    cache.delete(_cle_identifiant(identifiant))


def message_blocage():
    return (f"Trop de tentatives de connexion. Pour protéger les comptes, la connexion est suspendue "
            f"{settings.CONNEXION_BLOCAGE_MINUTES} minutes. Vous pouvez aussi réinitialiser votre mot de passe.")


def consigner(evenement, request=None, utilisateur=None, identifiant=""):
    """Ajoute une entrée au journal des connexions. Ne lève jamais d'exception : le journal ne bloque pas l'accès."""
    from .models import JournalConnexion

    try:
        JournalConnexion.objects.create(
            evenement=evenement,
            utilisateur=utilisateur if getattr(utilisateur, "pk", None) else None,
            identifiant=(identifiant or getattr(utilisateur, "username", "") or "")[:150],
            adresse_ip=adresse_ip(request),
            navigateur=(request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:200],
        )
    except Exception:  # base injoignable : on journalise dans la console et on continue
        journal.exception("Journal des connexions indisponible (%s, %s)", evenement, identifiant)
