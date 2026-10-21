"""Dossier médical : ce que le médecin doit savoir avant la consultation (logique pure, sans base de données)."""

# (libellé, adresse du formulaire où le compléter) ; tout se complète depuis « Mon profil » sauf les allergies et mesures
CONTROLES = (
    ("Groupe sanguin", lambda p, d: bool(d and d.groupe_sanguin)),
    ("Antécédents médicaux", lambda p, d: bool(d and d.antecedents.strip())),
    ("Traitements en cours", lambda p, d: bool(d and d.traitements_en_cours.strip())),
    ("Contact en cas d'urgence", lambda p, d: bool(p.contact_urgence_nom.strip() and p.contact_urgence_tel.strip())),
)


def elements_manquants(patient, dossier):
    """Libellés des informations utiles au médecin qui ne sont pas encore renseignées."""
    return [libelle for libelle, est_rempli in CONTROLES if not est_rempli(patient, dossier)]


def derniere_mesure_par_type(mesures):
    """Pour chaque type de mesure, la plus récente. `mesures` : n'importe quel ordre. Garde l'ordre des types."""
    plus_recentes = {}
    for m in mesures:
        if m.type not in plus_recentes or m.mesure_le > plus_recentes[m.type].mesure_le:
            plus_recentes[m.type] = m
    return list(plus_recentes.values())
