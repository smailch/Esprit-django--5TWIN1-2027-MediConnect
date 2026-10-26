"""Envoi du compte rendu par WhatsApp au clic du médecin.

L'API Cloud part du numéro relié à WHATSAPP_PHONE_ID.
Le patient reçoit sur le téléphone enregistré dans son dossier.
"""

import json
import urllib.error
import urllib.request

from django.conf import settings

from patients.visio import lien as lien_visio

from .sms import (
    EchecEnvoi,
    afficher_numero,
    message_compte_rendu,
    numero_expediteur,
    numero_sms,
)

LONGUEUR = 3500
GRAPH = "https://graph.facebook.com"


def numero_patient(consultation):
    """Téléphone du dossier patient, jamais un numéro d'essai fixe."""
    patient = getattr(consultation, "patient", None)
    return numero_sms(getattr(patient, "telephone", ""))


def _texte_pour(consultation, telephone_medecin=""):
    destinataire = numero_patient(consultation)
    expediteur = numero_expediteur() or numero_sms(telephone_medecin)
    return destinataire, message_compte_rendu(
        consultation,
        afficher_numero(destinataire),
        afficher_numero(expediteur),
        limite=LONGUEUR,
    )


def envoyer_compte_rendu(consultation, telephone_medecin=""):
    """Envoie le compte rendu. Retourne le numéro affiché au médecin."""
    numero, texte = _texte_pour(consultation, telephone_medecin)
    if not numero:
        raise EchecEnvoi("Ce patient n'a pas de numéro utilisable pour WhatsApp.")
    jeton = (getattr(settings, "WHATSAPP_TOKEN", "") or "").strip()
    numero_id = (getattr(settings, "WHATSAPP_PHONE_ID", "") or "").strip()
    if not jeton or not numero_id:
        raise EchecEnvoi("WhatsApp n'est pas configuré : le jeton ou l'identifiant du numéro manque.")
    _envoyer_texte(numero, texte)
    return {"mode": "api", "numero": numero, "affichage": afficher_numero(numero)}


def notifier_lancement(triage, nom_medecin):
    """Prévient le patient que sa consultation vient de commencer."""
    patient = getattr(triage, "patient", None)
    numero = numero_sms(getattr(patient, "telephone", ""))
    if not numero:
        raise EchecEnvoi("Ce patient n'a pas de numéro utilisable pour WhatsApp.")
    medecin = (nom_medecin or "").strip() or "Votre médecin"
    texte = (
        f"MediConnect : {medecin} a lancé votre consultation.\n"
        f"Rejoignez la salle : {lien_visio(triage)}"
    )
    _envoyer_texte(numero, texte)
    return {"numero": numero, "affichage": afficher_numero(numero)}


def _envoyer_texte(numero, texte):
    jeton = (getattr(settings, "WHATSAPP_TOKEN", "") or "").strip()
    numero_id = (getattr(settings, "WHATSAPP_PHONE_ID", "") or "").strip()
    if not jeton or not numero_id:
        raise EchecEnvoi("WhatsApp n'est pas configuré : le jeton ou l'identifiant du numéro manque.")
    version = (getattr(settings, "WHATSAPP_VERSION", "") or "v25.0").strip()
    try:
        _poster(f"{GRAPH}/{version}/{numero_id}/messages", _charge_message(numero, texte), jeton)
    except urllib.error.HTTPError as erreur:
        code, message = _detail(erreur)
        if code == 133010 and _enregistrer(jeton, numero_id, version):
            try:
                _poster(f"{GRAPH}/{version}/{numero_id}/messages", _charge_message(numero, texte), jeton)
            except urllib.error.HTTPError as encore:
                raise EchecEnvoi(_message_depuis(*_detail(encore))) from encore
            except urllib.error.URLError as erreur_reseau:
                raise EchecEnvoi("WhatsApp est injoignable. Réessayez dans un instant.") from erreur_reseau
        else:
            raise EchecEnvoi(_message_depuis(code, message)) from erreur
    except urllib.error.URLError as erreur:
        raise EchecEnvoi("WhatsApp est injoignable. Réessayez dans un instant.") from erreur


def _charge_message(numero, texte):
    return json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": numero,
        "type": "text",
        "text": {"preview_url": False, "body": texte},
    }).encode()


def _enregistrer(jeton, numero_id, version):
    """Enregistre le numéro chez Meta. Sans cela, l'envoi répond 133010."""
    code = (getattr(settings, "WHATSAPP_PIN", "") or "").strip()
    if len(code) != 6 or not code.isdigit():
        return False
    try:
        _poster(
            f"{GRAPH}/{version}/{numero_id}/register",
            json.dumps({"messaging_product": "whatsapp", "pin": code}).encode(),
            jeton,
        )
    except (urllib.error.HTTPError, urllib.error.URLError):
        return False
    return True


def _poster(url, charge, jeton):
    requete = urllib.request.Request(
        url,
        data=charge,
        headers={"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=20) as reponse:
        reponse.read()


def _message_refus(erreur):
    return _message_depuis(*_detail(erreur))


def _message_depuis(code, message):
    if code == 133010:
        return "Le numéro WhatsApp n'est pas enregistré chez Meta. Réessayez dans un instant."
    if code in (190, 102):
        return "Le jeton WhatsApp a expiré. Régénérez-le dans Meta, étape 1, puis redémarrez l'application."
    if code == 131030:
        return (
            "Ce numéro n'est pas autorisé pour l'essai. "
            "Ajoutez-le comme destinataire dans Meta, étape 1."
        )
    if code in (131047, 131026, 470):
        return (
            "WhatsApp n'accepte ce texte que si le patient a d'abord écrit "
            "au numéro de test dans les dernières 24 heures."
        )
    if message:
        return f"WhatsApp a refusé l'envoi : {message[:180]}"
    return "WhatsApp a refusé l'envoi."


def _detail(erreur):
    try:
        corps = json.loads(erreur.read().decode("utf-8", "replace"))
        erreur_api = corps.get("error") or {}
        return erreur_api.get("code"), (erreur_api.get("message") or "")
    except (json.JSONDecodeError, UnicodeError, AttributeError):
        return None, ""


def numero_expediteur_affiche():
    return afficher_numero(numero_sms(getattr(settings, "WHATSAPP_FROM", "") or ""))


def contexte_envoi(consultation):
    if not getattr(consultation, "pk", None):
        return {"whatsapp": False, "telephone": "", "expediteur": ""}
    numero = numero_patient(consultation)
    if numero:
        telephone = afficher_numero(numero)
    else:
        patient = getattr(consultation, "patient", None)
        telephone = getattr(patient, "telephone", "") or ""
    jeton = (getattr(settings, "WHATSAPP_TOKEN", "") or "").strip()
    numero_id = (getattr(settings, "WHATSAPP_PHONE_ID", "") or "").strip()
    return {
        "whatsapp": bool(numero and jeton and numero_id),
        "telephone": telephone,
        "expediteur": numero_expediteur_affiche() or "le numéro WhatsApp",
    }
