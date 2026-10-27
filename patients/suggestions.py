"""Proposition d'un médecin disponible aux patients très urgents.

Le système PROPOSE, le patient DÉCIDE : rien n'est modifié sans son accord.
"""

NIVEAU_MAX_PROPOSITION = 2  # niveaux 1 (vital) et 2 (très urgent)
LIMITE_PAR_DEFAUT = 3


def est_eligible(niveau):
    return niveau is not None and niveau <= NIVEAU_MAX_PROPOSITION


def _devant(niveau, niveaux_file):
    """Nombre de patients qui passeraient avant une demande de ce niveau :
    ceux de niveau égal (arrivés avant) ou plus urgent."""
    return sum(1 for n in niveaux_file if (n or 5) <= niveau)


def choisir_alternatives(niveau, courant, medecins, files, limite=LIMITE_PAR_DEFAUT):
    """Renvoie la liste (classée) des médecins à proposer.

    niveau   : niveau d'urgence effectif de la demande (1 ou 2).
    courant  : dict du médecin choisi par le patient.
    medecins : liste de dicts (id, nom, specialite, ville, disponible).
    files    : {medecin_id: [niveaux des demandes en attente]}.

    Chaque élément renvoyé est un dict de médecin enrichi de `devant`
    (patients à passer avant) et `meme_specialite` / `meme_ville`.
    """
    if not est_eligible(niveau):
        return []

    devant_courant = _devant(niveau, files.get(courant["id"], []))
    courant_disponible = courant.get("disponible", True)

    candidats = []
    for m in medecins:
        if m["id"] == courant["id"] or not m.get("disponible"):
            continue
        devant = _devant(niveau, files.get(m["id"], []))
        # Inutile de proposer un médecin qui ne fait pas gagner de place,
        # sauf si le médecin choisi n'est pas disponible.
        if courant_disponible and devant >= devant_courant:
            continue
        candidats.append({
            **m,
            "devant": devant,
            "meme_specialite": m["specialite"] == courant["specialite"],
            "meme_ville": m["ville"] == courant["ville"],
        })

    candidats.sort(key=lambda m: (m["devant"], not m["meme_specialite"], not m["meme_ville"], m["nom"]))
    return candidats[:limite]
