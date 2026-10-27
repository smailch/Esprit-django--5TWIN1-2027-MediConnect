"""Statistiques et graphique d'évolution des mesures de santé (calculs purs, sans base de données)."""

LARGEUR, HAUTEUR = 600, 240
MARGE_G, MARGE_D, MARGE_H, MARGE_B = 58, 16, 16, 34
SEUIL_TENDANCE = 0.02  # au-delà de 2 % d'écart avec la moyenne précédente, on parle de hausse ou de baisse


def resume(valeurs):
    """Minimum, maximum, moyenne et tendance d'une série chronologique de nombres."""
    if not valeurs:
        return None
    tendance = ""
    if len(valeurs) >= 2:
        precedentes = valeurs[:-1]
        reference = sum(precedentes) / len(precedentes)
        tendance = "stable"
        if reference:
            ecart = (valeurs[-1] - reference) / abs(reference)
            if ecart > SEUIL_TENDANCE:
                tendance = "hausse"
            elif ecart < -SEUIL_TENDANCE:
                tendance = "baisse"
    return {
        "min": min(valeurs),
        "max": max(valeurs),
        "moyenne": round(sum(valeurs) / len(valeurs), 1),
        "nombre": len(valeurs),
        "tendance": tendance,
    }


def graphique(points, bas=None, haut=None):
    """Coordonnées d'une courbe pour un graphique SVG.

    `points` : liste chronologique de tuples (datetime, valeur, valeur2 ou None).
    `bas` / `haut` : zone de repère à dessiner (facultatifs). Renvoie None s'il y a moins de deux points.
    """
    if len(points) < 2:
        return None
    t0, t1 = points[0][0].timestamp(), points[-1][0].timestamp()
    if t1 <= t0:
        return None
    valeurs = [p[1] for p in points] + [p[2] for p in points if p[2] is not None]
    reperes = [r for r in (bas, haut) if r is not None]
    mini, maxi = min(valeurs + reperes), max(valeurs + reperes)
    marge = (maxi - mini) * 0.08 or 1
    mini, maxi = mini - marge, maxi + marge

    zone_x0, zone_x1 = MARGE_G, LARGEUR - MARGE_D
    zone_y0, zone_y1 = MARGE_H, HAUTEUR - MARGE_B

    def x(instant):
        return round(zone_x0 + (instant.timestamp() - t0) / (t1 - t0) * (zone_x1 - zone_x0), 1)

    def y(valeur):
        return round(zone_y1 - (valeur - mini) / (maxi - mini) * (zone_y1 - zone_y0), 1)

    def ligne(indice):
        return [(x(p[0]), y(p[indice])) for p in points if p[indice] is not None]

    lignes = [ligne(1)]
    if any(p[2] is not None for p in points):
        lignes.append(ligne(2))

    zone = None
    if bas is not None or haut is not None:
        haut_y = y(haut) if haut is not None else zone_y0
        bas_y = y(bas) if bas is not None else zone_y1
        zone = {"y": max(min(haut_y, bas_y), zone_y0), "hauteur": max(min(max(haut_y, bas_y), zone_y1) - max(min(haut_y, bas_y), zone_y0), 0)}

    return {
        "largeur": LARGEUR,
        "hauteur": HAUTEUR,
        "lignes": [{"points": " ".join(f"{px},{py}" for px, py in l), "sommets": l} for l in lignes],
        "zone": zone,
        "zone_x": zone_x0,
        "zone_largeur": zone_x1 - zone_x0,
        "axe_y": [
            {"y": y(maxi - marge), "texte": f"{maxi - marge:g}"},
            {"y": y(mini + marge), "texte": f"{mini + marge:g}"},
        ],
        "axe_y_bas": zone_y1,
        "premiere_date": points[0][0],
        "derniere_date": points[-1][0],
    }
