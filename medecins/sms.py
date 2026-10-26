"""Envoi du compte rendu par SMS au clic du médecin.

Pendant l'essai, le patient et le médecin utilisent le même numéro
(SMS_NUMERO_TEST). Avec un compte Twilio, le clic envoie le SMS.
Sans compte, le clic ouvre l'application SMS du téléphone, texte prêt.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils import timezone

INDICATIF = "216"
LONGUEUR_LOCALE = 8
LONGUEUR_SMS = 480


class EchecEnvoi(Exception):
    pass


def numero_sms(telephone):
    """Numéro international, chiffres seuls, ou None si le numéro est inutilisable."""
    chiffres = "".join(c for c in (telephone or "") if c.isdigit())
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if len(chiffres) == LONGUEUR_LOCALE:
        chiffres = INDICATIF + chiffres
    if len(chiffres) == len(INDICATIF) + LONGUEUR_LOCALE and chiffres.startswith(INDICATIF):
        return chiffres
    if 10 <= len(chiffres) <= 15:
        return chiffres
    return None


def afficher_numero(numero):
    if not numero:
        return ""
    if numero.startswith(INDICATIF) and len(numero) == len(INDICATIF) + LONGUEUR_LOCALE:
        reste = numero[len(INDICATIF):]
        return f"+{INDICATIF} {reste[:2]} {reste[2:5]} {reste[5:]}"
    return f"+{numero}"


def numero_essai():
    return numero_sms(getattr(settings, "SMS_NUMERO_TEST", "") or "")


def numero_expediteur():
    """Numéro qui envoie le SMS, affiché aussi comme téléphone du médecin."""
    return numero_sms(getattr(settings, "TWILIO_FROM", "") or "")


def numero_destinataire(consultation):
    """Numéro qui reçoit le SMS : l'essai s'il est défini, sinon celui du patient."""
    essai = numero_essai()
    if essai:
        return essai
    patient = getattr(consultation, "patient", None)
    return numero_sms(getattr(patient, "telephone", ""))


def message_compte_rendu(consultation, telephone_patient="", telephone_medecin="", limite=LONGUEUR_SMS):
    date = consultation.date
    if date and timezone.is_naive(date):
        date = timezone.make_aware(date, timezone.get_current_timezone())
    if date:
        date = timezone.localtime(date)
    medecin = consultation.medecin_nom or "Médecin"
    if getattr(consultation, "medecin_specialite", ""):
        medecin = f"{medecin} ({consultation.medecin_specialite})"
    if telephone_medecin:
        medecin = f"{medecin} · {telephone_medecin}"
    patient = str(consultation.patient)
    if telephone_patient:
        patient = f"{patient} · {telephone_patient}"
    lignes = [
        "MediConnect",
        f"Patient : {patient}",
        f"Date : {date:%d/%m/%Y %H:%M}" if date else "Date : —",
        f"Médecin : {medecin}",
        "",
    ]
    for libelle, valeur in (
        ("Motif", consultation.motif),
        ("Compte rendu", consultation.resume),
        ("Diagnostic", consultation.diagnostic),
        ("Prescription", consultation.prescription),
        ("Recommandations", consultation.recommandations),
    ):
        valeur = (valeur or "").strip()
        if valeur:
            lignes.append(f"{libelle} : {valeur}")
    texte = "\n".join(lignes).strip()
    if len(texte) > limite:
        texte = texte[: limite - 1].rstrip() + "…"
    return texte


def _texte_pour(consultation, telephone_medecin=""):
    destinataire = numero_destinataire(consultation)
    expediteur = numero_expediteur() or numero_sms(telephone_medecin)
    return destinataire, message_compte_rendu(
        consultation,
        afficher_numero(destinataire),
        afficher_numero(expediteur),
    )


def lien_compte_rendu(consultation, telephone_medecin=""):
    numero, texte = _texte_pour(consultation, telephone_medecin)
    if not numero:
        return None
    return f"sms:+{numero}?&body={urllib.parse.quote(texte)}"


def _identifiants_twilio():
    """Compte, utilisateur et secret. Le jeton du compte prime sur la clé API."""
    compte = getattr(settings, "TWILIO_ACCOUNT_SID", "") or ""
    jeton = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    if compte and jeton:
        return compte, compte, jeton
    cle = getattr(settings, "TWILIO_API_KEY_SID", "") or ""
    secret = getattr(settings, "TWILIO_API_KEY_SECRET", "") or ""
    if compte and cle and secret:
        return compte, cle, secret
    return "", "", ""


def envoyer_compte_rendu(consultation, telephone_medecin=""):
    """Envoie le compte rendu. Retourne le mode « api » ou « lien »."""
    numero, texte = _texte_pour(consultation, telephone_medecin)
    if not numero:
        raise EchecEnvoi("Ce patient n'a pas de numéro utilisable pour un SMS.")
    affichage = afficher_numero(numero)
    mode = (getattr(settings, "SMS_MODE", "twilio") or "twilio").strip().lower()
    compte, utilisateur, secret = _identifiants_twilio()
    service = getattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "") or ""
    expediteur = getattr(settings, "TWILIO_FROM", "") or ""
    if mode == "twilio" and compte and utilisateur and secret and (service or expediteur):
        _envoyer_twilio(numero, texte, compte, utilisateur, secret, service, expediteur)
        return {"mode": "api", "numero": numero, "affichage": affichage}
    return {
        "mode": "lien",
        "numero": numero,
        "affichage": affichage,
        "lien": f"sms:+{numero}?&body={urllib.parse.quote(texte)}",
    }


def _envoyer_twilio(numero, texte, compte, utilisateur, secret, service, expediteur):
    champs = {"To": f"+{numero}", "Body": texte}
    if service:
        champs["MessagingServiceSid"] = service
    if expediteur:
        if not expediteur.startswith("+"):
            expediteur = f"+{expediteur}"
        champs["From"] = expediteur
    charge = urllib.parse.urlencode(champs).encode()
    autorisation = base64.b64encode(f"{utilisateur}:{secret}".encode()).decode()
    requete = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{compte}/Messages.json",
        data=charge,
        headers={"Authorization": f"Basic {autorisation}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=15) as reponse:
            reponse.read()
    except urllib.error.HTTPError as erreur:
        raise EchecEnvoi(_message_refus(erreur)) from erreur
    except urllib.error.URLError as erreur:
        raise EchecEnvoi("Le service SMS est injoignable. Réessayez dans un instant.") from erreur


def _message_refus(erreur):
    try:
        detail = json.loads(erreur.read().decode("utf-8", "replace"))
        message = detail.get("message") or ""
    except (json.JSONDecodeError, UnicodeError, AttributeError):
        message = ""
    if message:
        return f"Le SMS a été refusé : {message[:180]}"
    return "Le SMS a été refusé."


def contexte_envoi(consultation):
    if not getattr(consultation, "pk", None):
        return {"sms": False, "telephone": "", "essai": False}
    numero = numero_destinataire(consultation)
    essai = bool(numero_essai())
    if numero:
        telephone = afficher_numero(numero)
    else:
        patient = getattr(consultation, "patient", None)
        telephone = getattr(patient, "telephone", "") or ""
    return {
        "sms": bool(numero),
        "telephone": telephone,
        "expediteur": afficher_numero(numero_expediteur()),
        "essai": essai,
    }
