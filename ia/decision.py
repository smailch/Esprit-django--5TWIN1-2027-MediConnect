"""Comment l'avis du modèle est combiné aux règles (logique pure).

Règle d'or : le modèle ne peut que RELEVER l'urgence, jamais la baisser, et seulement s'il est sûr de lui.
Il ne décide jamais d'un cas vital (niveau 1) : ce niveau reste celui des règles (signes d'alerte) et du médecin.
"""

NIVEAU_LE_PLUS_URGENT_PAR_LE_MODELE = 2
SEUIL_PAR_DEFAUT = 0.85  # confiance minimale (85 %), réglable dans les Paramètres du back-office


def relever(niveau_regles, prediction, seuil=SEUIL_PAR_DEFAUT):
    """(niveau final, relevé ?). `prediction` : sortie de modele.predire (ou None)."""
    if not prediction or niveau_regles is None:
        return niveau_regles, False
    propose = max(prediction["niveau"], NIVEAU_LE_PLUS_URGENT_PAR_LE_MODELE)
    if prediction["confiance"] >= seuil and propose < niveau_regles:
        return propose, True
    return niveau_regles, False


def phrase_explicative(prediction, niveau_final):
    """Ce que l'explication de la demande dit quand le modèle a relevé le niveau."""
    mots = ", ".join(f"« {m} »" for m in prediction.get("mots") or [])
    return (
        f" Le modèle de lecture du texte a estimé un niveau {prediction['niveau']} ({round(prediction['confiance'] * 100)} % de confiance)"
        f"{' à cause de : ' + mots if mots else ''} : le niveau a été relevé à {niveau_final} (à confirmer par le médecin)."
    )
