"""De la consultation à l'ordonnance : le médecin envoie au patient les médicaments qu'il a prescrits.

Seuls les MÉDICAMENTS partent vers la pharmacie : les examens de laboratoire et les soins à domicile, prescrits
dans la même consultation, relèvent d'autres modules. L'IA lit la prescription et n'en extrait que les médicaments
(voir ia_extraction) ; sans IA (ou sans l'accord du patient), les règles ci-dessous prennent le relais. Le patient
retrouve l'ordonnance dans « Mes ordonnances » et choisit la pharmacie qui la préparera.
"""
from django.utils import timezone

from . import ia_extraction
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


def _sans_rubriques(texte):
    return (texte or "").strip()


def texte_source(consultation):
    """(texte à lire, extraction par les règles) : l'acte « Ordonnance » du module médecins s'il existe (déjà réservé
    aux médicaments), sinon le texte complet de la prescription (médicaments, examens et soins mêlés)."""
    actes = getattr(consultation, "actes", None)
    if actes is not None:
        acte = actes.filter(type=TITRE_ORDONNANCE).first()
        if acte is not None and acte.contenu.strip():
            return acte.contenu.strip(), _sans_rubriques
    return (consultation.prescription or "").strip(), extraire_medicaments


def a_une_prescription(consultation):
    """La consultation a-t-elle un texte de prescription ? (affichage du bouton : sans appel à l'IA)"""
    return bool(texte_source(consultation)[0])


def medicaments_de(consultation, *, identifiant=None):
    """Les médicaments de la consultation, extraits par l'IA (si le patient l'accepte) ou par les règles."""
    texte, regles = texte_source(consultation)
    return ia_extraction.extraire(
        texte, regles, consentement=bool(getattr(consultation.patient, "consentement_ia", False)), identifiant=identifiant
    )


def ordonnance_de(consultation):
    """L'ordonnance déjà envoyée pour cette consultation (hors annulée), ou None : on n'en crée jamais deux."""
    return (
        Ordonnance.objects.filter(consultation=consultation)
        .exclude(statut=Ordonnance.Statut.ANNULEE)
        .order_by("-cree_le")
        .first()
    )


def envoyer(consultation, *, identifiant=None):
    """Crée l'ordonnance « émise » du patient à partir de la consultation. Renvoie (ordonnance, extraction).

    Lève ValueError si c'est impossible (déjà envoyée, aucun médicament)."""
    deja = ordonnance_de(consultation)
    if deja is not None:
        raise ValueError(f"L'ordonnance de cette consultation a déjà été envoyée ({deja.reference}).")
    extraction = medicaments_de(consultation, identifiant=identifiant)
    if not extraction.lignes:
        if extraction.source == ia_extraction.IA:
            raise ValueError("L'IA n'a trouvé aucun médicament dans la prescription (seulement des examens, des soins ou des "
                             "conseils ?) : il n'y a pas d'ordonnance à envoyer. Vérifiez la rubrique « Ordonnance ».")
        raise ValueError("Aucun médicament n'est prescrit dans cette consultation : il n'y a pas d'ordonnance à envoyer.")
    ordonnance = Ordonnance(
        patient=consultation.patient, consultation=consultation, prescripteur_nom=consultation.medecin_nom,
        medicaments="\n".join(extraction.lignes), date_emission=timezone.localtime(consultation.date).date(),  # jour de la consultation
    )
    ordonnance.full_clean(exclude=["pharmacie", "ordonnance_origine", "pharmacie_reste"])  # mêmes règles que le formulaire
    ordonnance.save()
    return ordonnance, extraction
