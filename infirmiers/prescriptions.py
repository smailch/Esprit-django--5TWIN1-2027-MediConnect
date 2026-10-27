"""Soins à domicile prescrits par le médecin (module medecins, prescriptions de type « soin »).

Le patient voit les soins prescrits qu'il n'a pas encore demandés et peut les demander en un clic : le formulaire est
pré-rempli (texte du médecin, consultation d'origine, type de soin et répétition devinés), il vérifie l'adresse et la date.
La demande n'est jamais créée sans lui : lui seul connaît son adresse et ses disponibilités.
"""
import re

from patients.analyse_dossier import normaliser
from patients.models import Consultation

from .forms import PASSAGES_MAX
from .models import InterventionDomicile, TypeSoin

# Mots du texte du médecin -> type de soin (le premier trouvé l'emporte, dans cet ordre).
MOTS_DU_SOIN = (
    (TypeSoin.PERFUSION, ("perfusion",)),
    (TypeSoin.PRELEVEMENT, ("prise de sang", "prelevement", "bilan sanguin", "bilan", "nfs", "glycemie a jeun")),
    (TypeSoin.PANSEMENT, ("pansement", "plaie", "ulcere", "cicatrice", "escarre", "fils")),
    (TypeSoin.INJECTION, ("injection", "piqure", "anticoagulant", "lovenox", "insuline", "vaccin", "intramusculaire", "sous cutanee")),
    (TypeSoin.SURVEILLANCE, ("surveillance", "tension", "constantes", "glycemie", "saturation")),
    (TypeSoin.HYGIENE, ("toilette", "hygiene")),
)


def deviner_type_soin(texte):
    t = f" {normaliser(texte)} "
    for type_soin, mots in MOTS_DU_SOIN:
        if any(f" {mot} " in t for mot in mots):
            return type_soin
    return TypeSoin.AUTRE


def deviner_repetition(texte):
    """(répétition, nombre de passages) lus dans « chaque matin pendant 10 jours », « tous les 2 jours pendant 3 semaines »…
    (\"\", None) si le texte ne parle pas d'une série."""
    t = normaliser(texte)
    duree = re.search(r"pendant (\d+) (jour|jours|semaine|semaines)", t)
    if not duree:
        return "", None
    jours = int(duree.group(1)) * (7 if duree.group(2).startswith("semaine") else 1)
    if re.search(r"tous les (2|deux) jours|un jour sur deux", t):
        ecart = 2
    elif re.search(r"chaque semaine|une fois par semaine|toutes les semaines|hebdomadaire", t):
        ecart = 7
    else:
        ecart = 1  # « chaque matin », « tous les jours », « pendant 10 jours » : un passage par jour
    nombre = max(2, min(PASSAGES_MAX, -(-jours // ecart)))
    return str(ecart), nombre


def soins_prescrits(patient):
    """Prescriptions de soins à domicile du patient, de la plus récente à la plus ancienne, avec pour chacune la
    demande déjà faite à partir de sa consultation (ou None)."""
    from medecins.models import Prescription  # le module médecins est facultatif pour le reste de l'app

    consultations = {c.pk: c for c in Consultation.objects.filter(patient=patient)}
    if not consultations:
        return []
    prescriptions = Prescription.objects.filter(type=Prescription.Type.SOIN, consultation_id__in=list(consultations))
    demandes = {}
    for i in InterventionDomicile.objects.filter(patient=patient, consultation_id__in=list(consultations)):
        if i.statut != InterventionDomicile.Statut.ANNULEE:
            demandes.setdefault(i.consultation_id, i)
    resultat = [
        {"prescription": p, "consultation": consultations[p.consultation_id], "demande": demandes.get(p.consultation_id)}
        for p in prescriptions if (p.contenu or "").strip()
    ]
    return sorted(resultat, key=lambda r: r["prescription"].cree_le, reverse=True)


def valeurs_initiales(prescription):
    repetition, nombre = deviner_repetition(prescription.contenu)
    return {
        "type_soin": deviner_type_soin(prescription.contenu),
        "description": prescription.contenu.strip()[:1000],
        "consultation": prescription.consultation_id,
        "repetition": repetition,
        "nombre_passages": nombre,
    }
