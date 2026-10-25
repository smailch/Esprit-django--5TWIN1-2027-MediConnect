"""E-mails envoyés au patient quand son rendez-vous est FIXÉ (jour et heure), modifié, retardé ou annulé.

Pas d'e-mail pour une simple estimation (position dans la file, attente estimée) : elle change à chaque
arrivée de patient et se suit dans l'application. Aucune donnée médicale dans le message (symptômes, niveau
d'urgence, raison d'un retard) : un e-mail peut être lu par quelqu'un d'autre. Un échec d'envoi ne bloque jamais le rendez-vous.

Chaque message part en deux versions (texte et HTML) construites sur les gabarits `patients/email/<nom>.txt` et `.html`.
"""
import logging

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .agenda import SEUIL_ANNONCE_MIN, retard_minutes

journal = logging.getLogger(__name__)


def _envoyer(triage, objet, modele, lien=None, **contexte):
    """Envoie le message au patient de la demande ; renvoie True s'il est parti."""
    utilisateur = triage.patient.user
    if not utilisateur.email:
        return False
    contexte.update(user=utilisateur, triage=triage, creneau=triage.creneau, lien=lien)
    message = EmailMultiAlternatives(f"{objet} — MediConnect", render_to_string(f"{modele}.txt", contexte), None, [utilisateur.email])
    message.attach_alternative(render_to_string(f"{modele}.html", contexte), "text/html")
    try:
        return message.send(fail_silently=False) == 1
    except Exception:  # un serveur de messagerie en panne ne doit pas empêcher de réserver
        journal.exception("Envoi de l'e-mail de rendez-vous impossible (demande %s)", triage.pk)
        return False


def rendez_vous_fixe(triage, lien, modifie=False):
    """Confirmation du jour et de l'heure ; `modifie` : l'heure remplace une précédente."""
    if not triage.creneau:
        return False
    objet = "Votre rendez-vous a été modifié" if modifie else "Votre rendez-vous est confirmé"
    return _envoyer(triage, objet, "patients/email/rendez_vous_fixe", lien, modifie=modifie)


def rendez_vous_annule(triage, lien=None):
    """Annulation d'un rendez-vous fixé, ou d'une demande de la file dont le patient avait été prévenu (sinon il n'y a
    rien à annuler par e-mail). `lien` mène à une nouvelle demande."""
    if triage.creneau:
        return _envoyer(triage, "Votre rendez-vous est annulé", "patients/email/rendez_vous_annule", lien)
    if triage.heure_annoncee:
        return _envoyer(triage, "Votre demande est annulée", "patients/email/rendez_vous_annule", lien)
    return False


def demande_en_file(triage, prevue, place, lien, peut_choisir=False):
    """La demande est enregistrée dans la file du médecin : place et heure ESTIMÉE (pas d'heure fixée).
    `peut_choisir` : le patient pourrait encore réserver un créneau."""
    return _envoyer(triage, "Votre demande est enregistrée", "patients/email/demande_en_file", lien,
                    prevue=prevue, place=place, peut_choisir=peut_choisir)


def estimation_modifiee(triage, annoncee, prevue, lien):
    """L'heure estimée d'un patient de la file a beaucoup changé."""
    return _envoyer(triage, "Votre heure estimée a changé", "patients/email/estimation_modifiee", lien,
                    annoncee=annoncee, prevue=prevue, plus_tot=prevue < annoncee)


def rendez_vous_decale(triage, prevue, lien):
    """L'heure PRÉVUE d'un rendez-vous fixé a changé (retard, ou retour à l'heure fixée). Ne dit pas pourquoi."""
    retard = retard_minutes(triage.creneau, prevue)
    a_l_heure = retard < SEUIL_ANNONCE_MIN
    objet = "Votre rendez-vous retrouve son heure" if a_l_heure else "Votre rendez-vous est retardé"
    return _envoyer(triage, objet, "patients/email/rendez_vous_decale", lien, prevue=prevue, retard=retard, a_l_heure=a_l_heure)
