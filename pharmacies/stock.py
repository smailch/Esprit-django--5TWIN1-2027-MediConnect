"""Rapprochement entre les lignes d'une ordonnance et le stock d'une pharmacie.

Logique pure (listes en mémoire), sauf `retirer_du_stock` qui écrit en base. Une ligne d'ordonnance est rapprochée :
1. d'un médicament du stock portant le même nom (« Doliprane 1 g… » -> Doliprane) ;
2. sinon d'un médicament de même principe actif : une ordonnance écrite en DCI (« Paracétamol 1 g ») se sert avec
   la marque disponible. Parmi plusieurs candidats, celui qui a le plus de boîtes.
"""
from django.db.models import F

from patients.analyse_dossier import normaliser

from .ia_substitution import nettoyer
from .models import Medicament

INCONNU = "inconnu"  # la ligne ne correspond à aucun médicament du stock
LIBELLES = {Medicament.RUPTURE: "Rupture", Medicament.STOCK_BAS: "Stock bas", Medicament.DISPONIBLE: "En stock", INCONNU: "Non référencé"}


def _cle(texte):
    return normaliser(nettoyer(texte))


def trouver(texte, medicaments):
    """Le médicament du stock qui correspond à `texte` (ligne d'ordonnance ou nom), ou None."""
    cle = _cle(texte)
    if not cle:
        return None
    par_nom = [m for m in medicaments if _cle(m.nom) == cle]
    candidats = par_nom or [m for m in medicaments if m.principe_actif and normaliser(m.principe_actif) == cle]
    return max(candidats, key=lambda m: m.quantite, default=None)


def etat_des_lignes(lignes, medicaments):
    """[{ligne, medicament, etat, libelle}] : ce que la pharmacie a (ou n'a pas) pour chaque ligne de l'ordonnance."""
    resultat = []
    for ligne in lignes:
        medicament = trouver(ligne, medicaments)
        etat = medicament.etat if medicament else INCONNU
        resultat.append({"ligne": ligne, "medicament": medicament, "etat": etat, "libelle": LIBELLES[etat]})
    return resultat


def lignes_en_rupture(etats):
    """Les lignes que la pharmacie ne peut pas servir avec son stock (rupture réelle ou médicament non référencé)."""
    return [e["ligne"] for e in etats if e["etat"] in (Medicament.RUPTURE, INCONNU)]


def principe_de(texte, medicaments):
    """Le principe actif d'une ligne, d'après le stock (vide si inconnu)."""
    medicament = trouver(texte, medicaments)
    if medicament and medicament.principe_actif:
        return medicament.principe_actif
    return ""


def equivalents_en_stock(principe, medicaments, exclure=None):
    """Médicaments DISPONIBLES (quantité > 0) du même principe actif, le mieux fourni d'abord. Calcul 100 % local."""
    cle = normaliser(principe)
    if not cle:
        return []
    trouves = [m for m in medicaments if m.quantite > 0 and normaliser(m.principe_actif) == cle and m != exclure]
    return sorted(trouves, key=lambda m: -m.quantite)


def annoter_stock(suggestions, medicaments):
    """Ajoute à chaque suggestion (de l'IA ou de la table locale) la quantité disponible dans CE stock (None : pas référencé),
    puis place les suggestions disponibles en premier : le pharmacien voit d'abord ce qu'il peut remettre tout de suite."""
    for s in suggestions:
        medicament = trouver(s["nom"], medicaments)
        s["stock"] = medicament.quantite if medicament else None
    return sorted(suggestions, key=lambda s: 0 if s["stock"] else 1)


def retirer_du_stock(etats):
    """À la délivrance : une boîte de moins pour chaque ligne servie depuis le stock.

    Mise à jour atomique en base (F) et conditionnelle (quantité > 0) : deux délivrances simultanées ne peuvent pas
    faire passer le stock sous zéro. Renvoie le nombre de lignes décomptées."""
    retires = 0
    for e in etats:
        medicament = e["medicament"]
        if medicament is not None and medicament.quantite > 0:
            retires += Medicament.objects.filter(pk=medicament.pk, quantite__gt=0).update(quantite=F("quantite") - 1)
    return retires
