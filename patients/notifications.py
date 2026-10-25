"""E-mails envoyés au patient quand son rendez-vous est FIXÉ (jour et heure) ou annulé.

Pas d'e-mail pour une simple estimation (position dans la file, attente estimée) : elle change à chaque
arrivée de patient et se suit dans l'application. Aucune donnée médicale dans le message (symptômes, niveau
d'urgence) : un e-mail peut être lu par quelqu'un d'autre. Un échec d'envoi ne bloque jamais le rendez-vous.
"""
import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string

journal = logging.getLogger(__name__)


def _envoyer(triage, objet, modele, lien=None):
    """Envoie le message au patient de la demande ; renvoie True s'il est parti."""
    utilisateur = triage.patient.user
    if not utilisateur.email:
        return False
    corps = render_to_string(modele, {"user": utilisateur, "triage": triage, "creneau": triage.creneau, "lien": lien})
    try:
        return send_mail(objet, corps, None, [utilisateur.email], fail_silently=False) == 1
    except Exception:  # un serveur de messagerie en panne ne doit pas empêcher de réserver
        journal.exception("Envoi de l'e-mail de rendez-vous impossible (demande %s)", triage.pk)
        return False


def rendez_vous_fixe(triage, lien, modifie=False):
    """Confirmation du jour et de l'heure ; `modifie` : l'heure remplace une précédente."""
    objet = "Votre rendez-vous a été modifié" if modifie else "Votre rendez-vous est confirmé"
    return _envoyer(triage, f"{objet} — MediConnect", "patients/email/rendez_vous_fixe.txt", lien) if triage.creneau else False


def rendez_vous_annule(triage):
    """Annulation d'un rendez-vous qui avait une heure fixée (sans heure fixée, il n'y a rien à annuler par e-mail)."""
    if not triage.creneau:
        return False
    return _envoyer(triage, "Votre rendez-vous est annulé — MediConnect", "patients/email/rendez_vous_annule.txt")
