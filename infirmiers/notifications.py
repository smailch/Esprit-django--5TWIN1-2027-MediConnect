"""E-mails des soins à domicile : au patient quand son passage est fixé, déplacé ou annulé et quand le compte rendu
est disponible ; à l'infirmier quand le patient annule un passage accepté.

Mêmes principes que patients/notifications.py : aucune donnée médicale dans le message (ni le soin, ni le compte
rendu, ni le motif d'une annulation) car un e-mail peut être lu par quelqu'un d'autre, deux versions (texte et HTML)
construites sur `infirmiers/email/<nom>.txt` et `.html`, et un échec d'envoi ne bloque jamais l'action.
"""
import logging

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from core import courriel

journal = logging.getLogger(__name__)


def _envoyer(utilisateur, intervention, objet, modele, lien, **contexte):
    """Envoie le message ; renvoie True s'il est parti."""
    if not utilisateur.email:
        return False
    contexte.update(user=utilisateur, intervention=intervention, infirmier=intervention.infirmier, lien=lien)
    gabarit = f"infirmiers/email/{modele}"
    message = EmailMultiAlternatives(f"{objet} — MediConnect", render_to_string(f"{gabarit}.txt", contexte), None, [utilisateur.email])
    message.attach_alternative(render_to_string(f"{gabarit}.html", contexte), "text/html")
    return courriel.envoyer(message, f"soin à domicile {intervention.pk}", journal)  # en tâche de fond avec Celery


def _au_patient(intervention, objet, modele, lien, **contexte):
    return _envoyer(intervention.patient.user, intervention, objet, modele, lien, **contexte)


def passage_fixe(intervention, lien, ancien=None):
    """L'infirmier a accepté la demande (ou déplacé le passage : `ancien` est alors l'heure remplacée)."""
    if intervention.date_prevue is None or intervention.infirmier is None:
        return False
    objet = "Le passage de l'infirmier a changé d'heure" if ancien else "Un infirmier a accepté votre demande"
    return _au_patient(intervention, objet, "passage_fixe", lien, ancien=ancien)


def passage_libere(intervention, lien, infirmier, ancien):
    """L'infirmier s'est désisté : la demande retourne aux infirmiers de la zone. `infirmier` et `ancien` : le
    passage qui n'aura pas lieu (l'intervention n'a plus d'infirmier ni d'heure)."""
    return _au_patient(intervention, "Votre demande est de nouveau proposée", "passage_libere", lien,
                       ancien_infirmier=infirmier, ancien=ancien)


def passage_annule(intervention, lien):
    """L'infirmier a annulé le passage (le motif reste dans l'application)."""
    return _au_patient(intervention, "Le passage de l'infirmier est annulé", "passage_annule", lien)


def compte_rendu_disponible(intervention, lien):
    return _au_patient(intervention, "Le compte rendu de votre soin est disponible", "compte_rendu", lien)


def annule_par_le_patient(intervention, lien):
    """Prévient l'infirmier qu'un passage de son planning n'aura pas lieu."""
    if intervention.infirmier is None or intervention.date_prevue is None:
        return False
    return _envoyer(intervention.infirmier.user, intervention, "Un passage a été annulé", "annule_par_le_patient", lien)


def serie_acceptee(interventions, lien):
    """Un infirmier a accepté plusieurs passages d'une série : un seul message qui les récapitule."""
    interventions = sorted(interventions, key=lambda i: i.date_prevue)
    premier = interventions[0]
    if premier.infirmier is None:
        return False
    return _au_patient(premier, "Un infirmier a accepté votre série de soins", "serie_acceptee", lien, passages=interventions)
