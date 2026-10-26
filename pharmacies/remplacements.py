"""Droit de substitution : la pharmacie propose un remplaçant au patient, qui accepte ou refuse.

S'il accepte, la ligne de l'ordonnance est réécrite : le NOM change, le dosage et la posologie prescrits par le
médecin sont gardés, et la ligne garde la mention du médicament d'origine. Rien n'est remplacé sans l'accord du patient.
"""
import re

from django.utils import timezone

from patients.analyse_dossier import FAMILLES, familles_de, normaliser

from . import stock
from .ia_substitution import nettoyer
from .models import Ordonnance, Remplacement

R = Remplacement.Statut
MODIFIABLES = (Ordonnance.Statut.TRANSMISE, Ordonnance.Statut.EN_PREPARATION, Ordonnance.Statut.PRETE)


def nouvelle_ligne(ligne, remplacant):
    """« Amoxicilline 1 g, matin et soir » + « Hiconcil 1 g » -> « Hiconcil 1 g, matin et soir (remplace Amoxicilline) »."""
    prescrit = nettoyer(ligne)
    nom = nettoyer(remplacant) or " ".join(remplacant.split())
    debut = re.match(re.escape(prescrit), ligne, re.I) if prescrit else None
    suite = ligne[debut.end():] if debut else ""
    return f"{nom}{suite} (remplace {prescrit or ligne})"


def risque_allergie(ligne, remplacant, principe, substances):
    """(famille touchée ou "", nouveau risque ?) pour un remplaçant, face aux allergies actives du patient.

    « Nouveau » : le médicament prescrit n'appartenait pas à cette famille. Un remplaçant de même principe actif partage
    la famille du médicament prescrit : le risque est déjà celui choisi par le médecin, on l'affiche sans bloquer."""
    familles_patient = set()
    for substance in substances:
        familles_patient.update(familles_de(substance))
    touchees = [f for f in familles_de(f"{remplacant}, {principe}") if f in familles_patient]
    if not touchees:
        return "", False
    return FAMILLES[touchees[0]][0], touchees[0] not in familles_de(f"{ligne}, {principe}")


def proposer(ordonnance, ligne, remplacant, source, medicaments, substances):
    """Enregistre la proposition (une seule en attente par ligne). Lève ValueError si elle n'est pas acceptable."""
    if ordonnance.statut not in (Ordonnance.Statut.TRANSMISE, Ordonnance.Statut.EN_PREPARATION):
        raise ValueError("Un remplaçant se propose pendant la préparation de l'ordonnance.")
    if ligne not in ordonnance.lignes:
        raise ValueError("Choisissez un médicament de l'ordonnance.")
    remplacant = " ".join((remplacant or "").split())[:100]
    if not nettoyer(remplacant):
        raise ValueError("Indiquez le remplaçant à proposer au patient.")
    if normaliser(nettoyer(remplacant)) == normaliser(nettoyer(ligne)):
        raise ValueError("Le remplaçant doit être un autre médicament que celui prescrit.")
    famille, nouveau = risque_allergie(ligne, remplacant, stock.principe_de(ligne, medicaments), substances)
    if nouveau:
        raise ValueError(
            f"Proposition refusée : {remplacant} fait partie des {famille}, auxquels le patient est allergique "
            "(le médicament prescrit n'en faisait pas partie)."
        )
    source = source if source in Remplacement.Source.values else Remplacement.Source.SAISIE
    en_attente = Remplacement.objects.filter(ordonnance=ordonnance, ligne_origine=ligne, statut=R.PROPOSE).first()
    if en_attente is not None:  # le pharmacien change d'avis avant la réponse : on remplace sa proposition
        en_attente.remplacant, en_attente.source, en_attente.alerte_allergie = remplacant, source, famille
        en_attente.save(update_fields=["remplacant", "source", "alerte_allergie"])
        return en_attente
    return Remplacement.objects.create(
        ordonnance=ordonnance, ligne_origine=ligne, remplacant=remplacant, source=source, alerte_allergie=famille
    )


def accepter(remplacement):
    """Le patient accepte : la ligne de l'ordonnance est réécrite avec le remplaçant."""
    ordonnance = remplacement.ordonnance
    if remplacement.statut != R.PROPOSE:
        raise ValueError("Vous avez déjà répondu à cette proposition.")
    if ordonnance.statut not in MODIFIABLES:
        raise ValueError("Cette ordonnance ne peut plus être modifiée.")
    lignes = ordonnance.lignes
    if remplacement.ligne_origine not in lignes:
        raise ValueError("L'ordonnance a été modifiée entre-temps : cette proposition n'est plus valable.")
    lignes[lignes.index(remplacement.ligne_origine)] = nouvelle_ligne(remplacement.ligne_origine, remplacement.remplacant)
    ordonnance.medicaments = "\n".join(lignes)
    ordonnance.save(update_fields=["medicaments", "modifie_le"])
    remplacement.statut, remplacement.decide_le = R.ACCEPTE, timezone.now()
    remplacement.save(update_fields=["statut", "decide_le"])


def refuser(remplacement):
    """Le patient refuse : l'ordonnance ne change pas (il peut encore accepter une délivrance partielle ou changer de pharmacie)."""
    if remplacement.statut != R.PROPOSE:
        raise ValueError("Vous avez déjà répondu à cette proposition.")
    remplacement.statut, remplacement.decide_le = R.REFUSE, timezone.now()
    remplacement.save(update_fields=["statut", "decide_le"])
