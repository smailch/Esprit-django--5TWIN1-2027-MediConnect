"""De la consultation à l'ordonnance : le médecin envoie au patient les médicaments qu'il a prescrits.

Seuls les MÉDICAMENTS partent vers la pharmacie : les examens de laboratoire et les soins à domicile, prescrits
dans la même consultation, relèvent d'autres modules. Le patient retrouve l'ordonnance dans « Mes ordonnances »
et choisit la pharmacie qui la préparera.
"""
from django.utils import timezone

from .models import Ordonnance

TITRE_ORDONNANCE = "ordonnance"
AUTRES_RUBRIQUES = ("examens de laboratoire", "soins à domicile")  # voir medecins.forms.composer_prescription


def extraire_medicaments(prescription):
    """La rubrique « Ordonnance » d'un texte de prescription (logique pure).

    Le module médecins compose : « Ordonnance\\n… \\n\\nExamens de laboratoire\\n… \\n\\nSoins à domicile\\n… ».
    Un texte sans rubriques (saisi d'un bloc) est pris en entier ; un texte qui n'a que des examens ou des soins
    ne contient aucun médicament."""
    lignes = [ligne.rstrip() for ligne in (prescription or "").strip().splitlines()]
    titres = [ligne.strip().lower() for ligne in lignes]
    if not lignes:
        return ""
    if titres[0] == TITRE_ORDONNANCE:
        bloc = []
        for ligne, titre in zip(lignes[1:], titres[1:]):
            if titre in AUTRES_RUBRIQUES:
                break
            bloc.append(ligne)
        return "\n".join(bloc).strip()
    if any(titre in AUTRES_RUBRIQUES for titre in titres):
        return ""
    return "\n".join(lignes).strip()


def medicaments_de(consultation):
    """Les médicaments prescrits : l'acte « Ordonnance » du module médecins s'il existe, sinon le texte du compte rendu."""
    actes = getattr(consultation, "actes", None)
    if actes is not None:
        acte = actes.filter(type=TITRE_ORDONNANCE).first()
        if acte is not None and acte.contenu.strip():
            return acte.contenu.strip()
    return extraire_medicaments(consultation.prescription)


def ordonnance_de(consultation):
    """L'ordonnance déjà envoyée pour cette consultation (hors annulée), ou None : on n'en crée jamais deux."""
    return (
        Ordonnance.objects.filter(consultation=consultation)
        .exclude(statut=Ordonnance.Statut.ANNULEE)
        .order_by("-cree_le")
        .first()
    )


def envoyer(consultation):
    """Crée l'ordonnance « émise » du patient à partir de la consultation. Lève ValueError si c'est impossible."""
    deja = ordonnance_de(consultation)
    if deja is not None:
        raise ValueError(f"L'ordonnance de cette consultation a déjà été envoyée ({deja.reference}).")
    medicaments = medicaments_de(consultation)
    if not medicaments:
        raise ValueError("Aucun médicament n'est prescrit dans cette consultation : il n'y a pas d'ordonnance à envoyer.")
    ordonnance = Ordonnance(
        patient=consultation.patient, consultation=consultation, prescripteur_nom=consultation.medecin_nom,
        medicaments=medicaments, date_emission=timezone.localtime(consultation.date).date(),  # le jour de la consultation
    )
    ordonnance.full_clean(exclude=["pharmacie", "ordonnance_origine", "pharmacie_reste"])  # mêmes règles que le formulaire
    ordonnance.save()
    return ordonnance
