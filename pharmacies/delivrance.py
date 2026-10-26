"""Délivrance d'une ordonnance, totale ou partielle, et orientation du patient vers une pharmacie qui a le reste.

Règle : la pharmacie ne remet que ce qu'elle a en stock. S'il manque des médicaments :
* l'ordonnance délivrée ne garde que les médicaments réellement remis (c'est la trace de la délivrance) ;
* les médicaments manquants partent sur une NOUVELLE ordonnance (reliée à la première), rendue au patient ;
* le patient voit les pharmacies qui ont ces médicaments en stock et l'y envoie en un clic.
"""
from django.utils import timezone

from . import stock
from .ia_substitution import nettoyer, suggestions_locales
from .models import Medicament, Ordonnance

S = Ordonnance.Statut
MAX_PHARMACIES = 3


def accord_demandable(ordonnance, etats):
    """La pharmacie peut demander l'accord du patient : il manque des médicaments, mais elle en a au moins un,
    et la délivrance n'a pas eu lieu."""
    return (
        ordonnance.statut in (S.TRANSMISE, S.EN_PREPARATION, S.PRETE)
        and ordonnance.accord_partiel == Ordonnance.Accord.NON_DEMANDE
        and bool(lignes_servies(etats)) and bool(stock.lignes_en_rupture(etats))
    )


def lignes_servies(etats):
    """Les lignes que la pharmacie peut remettre avec son stock."""
    return [e["ligne"] for e in etats if e["etat"] in (Medicament.DISPONIBLE, Medicament.STOCK_BAS)]


def delivrer(ordonnance, etats):
    """Délivre ce qui est en stock. Renvoie (boîtes retirées du stock, ordonnance du reste ou None).

    Lève ValueError si rien n'est disponible, ou si l'ordonnance ne peut pas être délivrée (statut, expiration)."""
    servies, manquantes = lignes_servies(etats), stock.lignes_en_rupture(etats)
    if not servies:
        raise ValueError(
            "Aucun médicament de cette ordonnance n'est dans votre stock : rien ne peut être délivré. "
            "Renvoyez-la au patient, il verra les pharmacies qui les ont."
        )
    if manquantes and ordonnance.accord_partiel != Ordonnance.Accord.ACCEPTE:
        raise ValueError("Il manque des médicaments : demandez d'abord l'accord du patient pour une délivrance partielle.")
    ordonnance.avancer()  # contrôle du statut et de l'expiration AVANT toute autre écriture
    reste = None
    if manquantes:
        reste = Ordonnance(
            patient_id=ordonnance.patient_id, consultation_id=ordonnance.consultation_id,
            prescripteur_nom=ordonnance.prescripteur_nom, medicaments="\n".join(manquantes),
            instructions=ordonnance.instructions, date_emission=ordonnance.date_emission,
            valide_jusqu_au=ordonnance.valide_jusqu_au,  # même ordonnance médicale : même validité
            ordonnance_origine=ordonnance,
            pharmacie_id=ordonnance.pharmacie_reste_id,  # choisie par le patient : le reste y est transmis d'office
            note_pharmacien=f"Reste à servir : non disponible chez {ordonnance.pharmacie} le {timezone.localdate():%d/%m/%Y}."[:300],
        )
        reste.save()
        ordonnance.medicaments = "\n".join(servies)
        ordonnance.note_pharmacien = (
            f"Délivrance partielle : {len(manquantes)} médicament(s) non disponible(s), "
            f"reporté(s) sur l'ordonnance {reste.reference}."
        )[:300]
        ordonnance.save(update_fields=["medicaments", "note_pharmacien", "modifie_le"])
    return stock.retirer_du_stock(etats), reste


def principes_des_lignes(lignes, medicaments):
    """{ligne: principe actif} : d'après les stocks connus (« Mopral » est de l'oméprazole), sinon la table locale."""
    principes = {}
    for ligne in lignes:
        principe = stock.principe_de(ligne, medicaments) or suggestions_locales(nettoyer(ligne))[0]
        if principe:
            principes[ligne] = principe
    return principes


def classer_pharmacies(lignes, groupes, ville="", limite=MAX_PHARMACIES, principes=None):
    """Pharmacies qui ont au moins un des médicaments demandés EN STOCK (logique pure).

    groupes : [(pharmacie, [médicaments de son stock])] ; principes : {ligne: principe actif}. Un médicament compte s'il
    est en stock sous le même nom OU avec le même principe actif. Classement : celles qui ont tout d'abord, puis le plus
    de médicaments, puis la ville du patient, puis les pharmacies de garde."""
    principes = principes or {}
    resultats = []
    for pharmacie, medicaments in groupes:
        disponibles = [m for m in medicaments if m.quantite > 0]
        trouvees = [
            ligne for ligne in lignes
            if stock.trouver(ligne, disponibles) or stock.equivalents_en_stock(principes.get(ligne, ""), disponibles)
        ]
        if trouvees:
            resultats.append({
                "pharmacie": pharmacie,
                "medicaments": [nettoyer(ligne) for ligne in trouvees],
                "nombre": len(trouvees),
                "complete": len(trouvees) == len(lignes),
            })
    ville = (ville or "").casefold()
    resultats.sort(key=lambda r: (-r["nombre"], r["pharmacie"].ville.casefold() != ville, not r["pharmacie"].de_garde, r["pharmacie"].nom))
    return resultats[:limite]


def pharmacies_disponibles(lignes, exclure=None, ville=""):
    """Les pharmacies (actives et validées) qui ont ces médicaments en stock, d'après leur stock réel."""
    if not lignes:
        return []
    # Une seule requête : tous les stocks des pharmacies actives (ceux à zéro servent à connaître les principes actifs).
    tous = list(Medicament.objects.filter(pharmacie__user__is_active=True, pharmacie__user__est_valide=True).select_related("pharmacie"))
    groupes = {}
    for m in tous:
        if exclure is None or m.pharmacie_id != exclure.pk:
            groupes.setdefault(m.pharmacie_id, (m.pharmacie, []))[1].append(m)
    return classer_pharmacies(lignes, groupes.values(), ville, principes=principes_des_lignes(lignes, tous))
