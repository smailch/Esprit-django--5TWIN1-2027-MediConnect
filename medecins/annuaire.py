"""Annuaire des médecins visibles par les patients : uniquement les profils validés."""


def _interdit_sans_base(exc):
    return exc.__class__.__name__ == "DatabaseOperationForbidden"


def tous():
    """Fiches des médecins validés et actifs. Liste vide si ce test n'a pas le droit d'ouvrir la base."""
    try:
        from .models import Medecin
        profils = Medecin.objects.filter(user__est_valide=True, user__is_active=True).select_related("user")
        return [m.vers_fiche() for m in profils]
    except Exception as exc:
        if _interdit_sans_base(exc):
            return []
        raise


def trouver(code):
    return next((m for m in tous() if m["id"] == code), None)


def filtrer(specialite="", ville="", fiches=None):
    source = tous() if fiches is None else fiches
    return [
        m
        for m in source
        if (not specialite or m["specialite"] == specialite)
        and (not ville or m["ville"] == ville)
    ]


def specialites():
    return sorted({m["specialite"] for m in tous()})


def villes():
    return sorted({m["ville"] for m in tous()})
