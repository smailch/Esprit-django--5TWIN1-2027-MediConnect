"""Prépare les données d'un patient pour l'analyse automatique de son dossier (lecture seule).

L'IA (facultative) lit le dossier médical COMPLET du patient (voir ia_dossier) : elle rattache ses textes libres et ses
allergies aux catégories connues, puis résume tout le dossier en langage simple. Trois modes : « aucun » (règles
seules), « cache » (reprend une analyse IA déjà faite, sans jamais contacter le service : pour les pages qui ne
doivent pas déclencher d'appel externe) et « complet »."""
from django.utils import timezone

from . import analyse_dossier, dossier as synthese, ia_client, ia_dossier, ia_taches
from .models import Allergie, DossierMedical, Mesure, Triage

AUCUN, CACHE, COMPLET = "aucun", "cache", "complet"


def _allergies(patient):
    return [
        {
            "substance": a.substance, "gravite": a.gravite, "active": a.active,
            "type": a.type, "reaction": a.reaction, "decouverte_le": a.decouverte_le,
        }
        for a in Allergie.objects.filter(patient=patient)
    ]


def _mesures(patient):
    return [
        {
            "type": m.type, "valeur": m.valeur, "valeur2": m.valeur2, "mesure_le": m.mesure_le,
            "note": m.note, "libelle": m.get_type_display(), "unite": m.unite,
        }
        for m in Mesure.objects.filter(patient=patient)
    ]


def _constantes(c):
    """Les mesures saisies dans une demande de rendez-vous, en phrases courtes."""
    if c is None:
        return []
    morceaux = []
    if c.temperature is not None:
        morceaux.append(f"température {c.temperature:g} °C")
    if c.tension_systolique is not None:
        diastole = f"/{c.tension_diastolique}" if c.tension_diastolique is not None else ""
        morceaux.append(f"tension {c.tension_systolique}{diastole} mmHg")
    if c.frequence_cardiaque is not None:
        morceaux.append(f"pouls {c.frequence_cardiaque} bpm")
    if c.saturation_oxygene is not None:
        morceaux.append(f"saturation {c.saturation_oxygene} %")
    return morceaux


def _ressenti(a):
    """L'auto-évaluation du patient (notes de 0 à 5)."""
    if a is None:
        return []
    notes = (("douleur", a.douleur), ("fièvre", a.fievre), ("respiration", a.respiration), ("état général", a.etat_general))
    return [f"{nom} {valeur}/5" for nom, valeur in notes if valeur is not None]


def _demandes(patient):
    """Les dernières demandes de rendez-vous du patient, de la plus récente à la plus ancienne."""
    recentes = sorted(Triage.objects.filter(patient=patient), key=lambda t: t.cree_le, reverse=True)[:ia_dossier.MAX_DEMANDES]
    return [
        {
            "date": t.cree_le, "niveau": t.niveau_effectif, "statut": t.get_statut_display().lower(),
            "symptomes": [s.nom for s in t.symptomes], "constantes": _constantes(t.constantes),
            "ressenti": _ressenti(t.auto_evaluation), "texte": t.texte_libre,
        }
        for t in recentes
    ]


def analyser_patient(patient, maintenant=None, ia=AUCUN):
    maintenant = maintenant or timezone.now()
    fiche = DossierMedical.objects.filter(patient=patient).first()
    allergies, mesures = _allergies(patient), _mesures(patient)
    antecedents = (fiche.antecedents if fiche else "") or ""
    traitements = (fiche.traitements_en_cours if fiche else "") or ""
    groupe_sanguin = fiche.groupe_sanguin if fiche else ""
    manquants = synthese.elements_manquants(patient, fiche)

    consenti = bool(getattr(patient, "consentement_ia", False))
    lit = ia != AUCUN and ia_client.est_active() and consenti  # l'IA ne lit le dossier que si le patient l'a accepté
    etat_ia = {
        "disponible": ia_client.est_active(), "consentement": consenti, "statut": "", "reformulation": "", "duree_ms": 0,
        "contenu_a_lire": bool(antecedents.strip() or traitements.strip() or allergies or mesures or groupe_sanguin),
        "lu": [], "envoye": "",  # ce que l'IA a lu, rubrique par rubrique, et le texte exact envoyé
    }
    extras, dossier_ia = None, None
    seulement_cache = ia == CACHE
    identifiant = str(patient.pk)
    if lit:
        dossier_ia = ia_dossier.composer(
            age=patient.age, sexe=patient.sexe, groupe_sanguin=groupe_sanguin, antecedents=antecedents,
            traitements=traitements, allergies=allergies, mesures=mesures, demandes=_demandes(patient),
            manquants=manquants, maintenant=maintenant,
        )
        etat_ia.update(contenu_a_lire=dossier_ia.a_du_contenu, lu=dossier_ia.lu, envoye=dossier_ia.texte)
        sortie = ia_taches.extraire_dossier(
            antecedents, traitements, dossier_ia.allergies, identifiant=identifiant, seulement_cache=seulement_cache
        )
        etat_ia["statut"], etat_ia["duree_ms"] = sortie.statut, sortie.duree_ms
        if sortie.ok:
            extras = sortie.elements

    analyse = analyse_dossier.analyser(
        age=patient.age,
        sexe=patient.sexe,
        groupe_sanguin=groupe_sanguin,
        antecedents=antecedents,
        traitements=traitements,
        allergies=allergies,
        mesures=mesures,
        manquants=manquants,
        total_controles=len(synthese.CONTROLES),
        maintenant=maintenant,
        extras=extras,
    )
    if lit and dossier_ia.a_du_contenu:
        reformulation = ia_taches.reformuler_analyse(
            analyse, dossier_ia.texte, identifiant=identifiant, seulement_cache=seulement_cache
        )
        etat_ia["reformulation"] = reformulation.statut
        if reformulation.ok:
            analyse.en_clair = reformulation.elements["en_clair"]
    analyse.ia = etat_ia
    return analyse
