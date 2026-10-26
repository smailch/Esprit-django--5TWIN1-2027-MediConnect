"""Salle Jitsi d'une demande : le médecin et le patient y entrent avec le même nom de salle.

meet.jit.si n'ouvre plus la réunion sans compte hôte, et l'appel reste bloqué
dans l'interface. Ce serveur accepte l'intégration et laisse le premier
participant démarrer la salle.
"""

DOMAINE = "meet.guifi.net"


def salle(triage):
    return f"mediconnect-{triage.pk}"


def lien(triage):
    return f"https://{DOMAINE}/{salle(triage)}"


def config(triage, nom):
    return {
        "domaine": DOMAINE,
        "salle": salle(triage),
        "nom": nom,
        "lien": lien(triage),
    }
