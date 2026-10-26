"""Statistiques du tableau de bord de la pharmacie (fonctions pures, testables sans base de données).

Chaque fonction reçoit les ordonnances de LA pharmacie connectée (objets avec statut, patient_id, medicaments,
modifie_le, delivree_le) : jamais celles des autres."""
import datetime
import re
from collections import Counter

from django.utils import timezone

from .models import Medicament, Ordonnance

S = Ordonnance.Statut
EN_COURS = (S.TRANSMISE, S.EN_PREPARATION, S.PRETE)
JOURS_AVANT_RELANCE = 3  # une ordonnance prête depuis plus longtemps n'a sans doute pas été retirée
JOURS_SEMAINE = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def _jour(moment):
    return timezone.localtime(moment).date() if moment else None


def chiffres_cles(ordonnances, aujourdhui=None):
    aujourdhui = aujourdhui or timezone.localdate()
    statuts = Counter(o.statut for o in ordonnances)
    delivrees = [o for o in ordonnances if o.statut == S.DELIVREE]
    jours = [_jour(o.delivree_le) for o in delivrees]
    traitees = statuts[S.DELIVREE] + statuts[S.ANNULEE]
    return {
        "a_preparer": statuts[S.TRANSMISE],
        "en_preparation": statuts[S.EN_PREPARATION],
        "pretes": statuts[S.PRETE],
        "delivrees_aujourdhui": sum(1 for j in jours if j == aujourdhui),
        "delivrees_mois": sum(1 for j in jours if j and (j.year, j.month) == (aujourdhui.year, aujourdhui.month)),
        "total": len(ordonnances),
        "patients_servis": len({o.patient_id for o in delivrees}),
        # part des ordonnances terminées qui ont bien été délivrées (et non annulées)
        "taux_delivrance": round(100 * statuts[S.DELIVREE] / traitees) if traitees else None,
    }


def _barres(lignes):
    """[(clé, libellé, nombre)] -> barres dont la longueur est relative à la plus grande."""
    maximum = max((n for _, _, n in lignes), default=0)
    return [
        {"cle": cle, "libelle": libelle, "nombre": n, "pourcentage": round(100 * n / maximum) if maximum else 0}
        for cle, libelle, n in lignes
    ]


def repartition_par_statut(ordonnances):
    statuts = Counter(o.statut for o in ordonnances)
    ordre = (S.TRANSMISE, S.EN_PREPARATION, S.PRETE, S.DELIVREE, S.ANNULEE)
    return _barres([(s, S(s).label, statuts[s]) for s in ordre])


def delivrees_par_jour(ordonnances, aujourdhui=None, jours=7):
    """Ordonnances délivrées chacun des `jours` derniers jours (aujourd'hui compris), du plus ancien au plus récent."""
    aujourdhui = aujourdhui or timezone.localdate()
    par_jour = Counter(_jour(o.delivree_le) for o in ordonnances if o.statut == S.DELIVREE)
    dates = [aujourdhui - datetime.timedelta(days=i) for i in range(jours - 1, -1, -1)]
    return _barres([(d, f"{JOURS_SEMAINE[d.weekday()]} {d:%d/%m}", par_jour[d]) for d in dates])


def nom_du_medicament(ligne):
    """« Amoxicilline 1 g, matin et soir » -> « Amoxicilline » : le nom s'arrête au premier chiffre ou à la virgule."""
    nom = re.split(r"[\d,;(]", ligne, maxsplit=1)[0].strip(" -•.")
    return nom[:1].upper() + nom[1:].lower() if nom else ""


def medicaments_frequents(ordonnances, limite=5):
    """Les médicaments les plus prescrits dans les ordonnances reçues (utile pour anticiper le stock)."""
    compteur = Counter()
    for o in ordonnances:
        if o.statut != S.ANNULEE:
            compteur.update({nom for nom in map(nom_du_medicament, o.lignes) if nom})  # une fois par ordonnance
    return _barres([(nom, nom, n) for nom, n in compteur.most_common(limite)])


def a_traiter(ordonnances, limite=6):
    """La file du comptoir : à préparer et en préparation, la plus ancienne d'abord (premier arrivé, premier servi)."""
    file = [o for o in ordonnances if o.statut in (S.TRANSMISE, S.EN_PREPARATION)]
    return sorted(file, key=lambda o: o.modifie_le)[:limite]


def chiffres_stock(medicaments, limite=6):
    """Le stock en un coup d'œil : nombre de références, ruptures, stocks bas, et la liste à commander
    (ruptures d'abord, puis les stocks les plus bas)."""
    etats = Counter(m.etat for m in medicaments)
    a_commander = sorted((m for m in medicaments if m.etat != Medicament.DISPONIBLE), key=lambda m: (m.quantite, m.nom.lower()))
    return {
        "references": len(medicaments),
        "rupture": etats[Medicament.RUPTURE],
        "bas": etats[Medicament.STOCK_BAS],
        "boites": sum(m.quantite for m in medicaments),
        "a_commander": a_commander[:limite],
    }


def a_relancer(ordonnances, maintenant=None):
    """Ordonnances prêtes depuis plus de JOURS_AVANT_RELANCE jours : le patient n'est peut-être pas prévenu."""
    limite = (maintenant or timezone.now()) - datetime.timedelta(days=JOURS_AVANT_RELANCE)
    return sorted((o for o in ordonnances if o.statut == S.PRETE and o.modifie_le < limite), key=lambda o: o.modifie_le)
