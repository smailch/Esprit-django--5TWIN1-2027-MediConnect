"""Le dossier médical complet, mis en texte pour l'IA (logique pure, sans base de données).

L'IA ne lit pas seulement quelques textes libres : elle reçoit TOUT ce que le médecin lit avant la consultation,
c'est-à-dire le profil (sexe, âge, groupe sanguin), les antécédents, les traitements, les allergies, les mesures
de santé, les comptes rendus des consultations passées et les dernières demandes de rendez-vous.

Ce qui n'est jamais envoyé : le nom, la date de naissance, le téléphone, l'adresse, la ville, l'e-mail et le contact
d'urgence (rien de cela n'aide à lire un dossier médical). Les numéros, e-mails et liens écrits dans les textes libres
sont retirés (voir ia_garde_fous.anonymiser). Chaque rubrique est bornée en taille : un dossier très chargé reste lisible.
"""
import datetime
from dataclasses import dataclass, field

from django.utils import timezone

from . import ia_garde_fous as gf

FENETRE_MESURES_JOURS = 180  # six mois de mesures
MESURES_PAR_TYPE = 6  # les plus récentes de chaque type : assez pour voir une tendance
MAX_DEMANDES = 5
MAX_CONSULTATIONS = 5
MAX_ALLERGIES = 20
LONGUEUR_ALLERGIE = 120  # substance et réaction, chacune
LONGUEUR_NOTE = 100
LONGUEUR_TEXTE_DEMANDE = 300
LONGUEUR_CONSULTATION = 300  # chaque champ d'un compte rendu
LONGUEUR_ALLERGIES = 4000

TYPES_ALLERGIE = {"medicament": "médicament", "aliment": "aliment", "environnement": "environnement", "autre": "autre"}
GRAVITES = {"legere": "légère", "moderee": "modérée", "severe": "sévère"}


@dataclass
class DossierIA:
    texte: str  # tout le dossier, tel qu'il est envoyé au modèle
    allergies: str = ""  # les allergies actives, une par ligne : le texte où l'IA doit citer ses extraits
    lu: list = field(default_factory=list)  # [(rubrique, détail, renseignée)] : ce que l'IA a lu, montré au patient
    a_du_contenu: bool = False  # y a-t-il autre chose que le sexe et l'âge ?


def _pluriel(n, mot, pluriel=None):
    return f"{n} {mot if n < 2 else (pluriel or mot + 's')}"


def _nombre(valeur):
    return f"{valeur:g}"


def _date(instant):
    """Jour local (et non UTC) : une mesure prise à 0 h 30 à Tunis appartient au jour même."""
    if timezone.is_aware(instant):
        instant = timezone.localtime(instant)
    return instant.strftime("%d/%m/%Y")


def _profil(age, sexe, groupe_sanguin):
    sexe_texte = "femme" if sexe == "F" else "homme" if sexe == "H" else "sexe inconnu"
    age_texte = f"{age} ans" if age is not None and age >= 0 else "âge inconnu"
    groupe = f", groupe sanguin {groupe_sanguin}" if groupe_sanguin else ""
    return f"{sexe_texte}, {age_texte}{groupe}"


def _allergies(allergies):
    """(lignes, texte des allergies actives, nombre d'allergies sévères actives)."""
    lignes, actives, severes = [], [], 0
    for a in allergies[:MAX_ALLERGIES]:
        substance = gf.anonymiser(a.get("substance"), LONGUEUR_ALLERGIE)
        if not substance:
            continue
        reaction = gf.anonymiser(a.get("reaction"), LONGUEUR_ALLERGIE)
        active = a.get("active", True)
        details = [TYPES_ALLERGIE.get(a.get("type"), a.get("type") or ""), GRAVITES.get(a.get("gravite"), a.get("gravite") or "")]
        details = [d for d in details if d]
        details.append("active" if active else "disparue (n'est plus d'actualité)")
        ligne = f"- {substance} ({', '.join(details)})"
        if reaction:
            ligne += f" ; réaction : {reaction}"
        if a.get("decouverte_le"):
            ligne += f" ; depuis {a['decouverte_le'].year}"
        lignes.append(ligne)
        if active:
            actives.append(f"{substance}. {reaction}" if reaction else substance)
            severes += a.get("gravite") == "severe"
    return lignes, "\n".join(actives), severes


def _mesures(mesures, maintenant):
    """(lignes, nombre de mesures retenues, nombre de types) : les plus récentes de chaque type, sur six mois."""
    debut = maintenant - datetime.timedelta(days=FENETRE_MESURES_JOURS)
    par_type = {}
    for m in sorted(mesures, key=lambda m: (m["mesure_le"], m["type"]), reverse=True):
        if m["mesure_le"] >= debut and len(par_type.setdefault(m["type"], [])) < MESURES_PAR_TYPE:
            par_type[m["type"]].append(m)
    lignes = []
    for type_, liste in sorted(par_type.items(), key=lambda element: element[1][0].get("libelle") or element[0]):
        morceaux = []
        for m in liste:
            valeur = _nombre(m["valeur"])
            if m.get("valeur2") is not None:
                valeur += f"/{_nombre(m['valeur2'])}"
            unite = m.get("unite") or ""
            note = gf.anonymiser(m.get("note"), LONGUEUR_NOTE)
            morceaux.append(f"{valeur} {unite}".strip() + f" le {_date(m['mesure_le'])}" + (f" ({note})" if note else ""))
        lignes.append(f"- {liste[0].get('libelle') or type_} : " + " ; ".join(morceaux))
    return lignes, sum(len(liste) for liste in par_type.values()), len(par_type)


def _demandes(demandes):
    lignes = []
    for d in sorted(demandes, key=lambda d: d["date"], reverse=True)[:MAX_DEMANDES]:
        morceaux = [f"{_date(d['date'])}"]
        niveau = f"urgence niveau {d['niveau']} sur 5" if d.get("niveau") else "niveau d'urgence non évalué"
        morceaux.append(niveau + (f" ({d['statut']})" if d.get("statut") else ""))
        if d.get("symptomes"):
            morceaux.append("symptômes déclarés : " + ", ".join(d["symptomes"]))
        if d.get("constantes"):
            morceaux.append("mesures saisies : " + ", ".join(d["constantes"]))
        if d.get("ressenti"):
            morceaux.append("ressenti : " + ", ".join(d["ressenti"]))
        texte = gf.anonymiser(d.get("texte"), LONGUEUR_TEXTE_DEMANDE)
        if texte:
            morceaux.append(f"texte du patient : « {texte} »")
        lignes.append("- " + " ; ".join(morceaux))
    return lignes


def _consultations(consultations):
    """Les comptes rendus récents, du plus récent au plus ancien. Jamais le nom du médecin."""
    lignes = []
    for c in sorted(consultations, key=lambda c: c["date"], reverse=True)[:MAX_CONSULTATIONS]:
        morceaux = [_date(c["date"])]
        for libelle, cle in (("motif", "motif"), ("compte rendu", "resume"), ("diagnostic", "diagnostic"),
                             ("prescription", "prescription"), ("recommandations", "recommandations")):
            texte = " ".join(gf.anonymiser(c.get(cle), LONGUEUR_CONSULTATION).split())
            if texte:
                morceaux.append(f"{libelle} : {texte}")
        lignes.append("- " + " ; ".join(morceaux))
    return lignes


def composer(*, age, sexe, groupe_sanguin, antecedents, traitements, allergies, mesures, demandes, manquants, maintenant,
             consultations=()):
    """Le dossier en texte. Mêmes données, même texte : c'est ce qui permet de réutiliser une réponse déjà obtenue.

    allergies : [{substance, type, gravite, reaction, decouverte_le, active}] ;
    mesures   : [{type, libelle, unite, valeur, valeur2, mesure_le, note}] ;
    demandes  : [{date, niveau, statut, symptomes, constantes, ressenti, texte}] (demandes de rendez-vous) ;
    manquants : libellés des informations utiles non renseignées ;
    consultations : [{date, motif, resume, diagnostic, prescription, recommandations}] (comptes rendus de consultations)."""
    antecedents_texte, traitements_texte = gf.anonymiser(antecedents), gf.anonymiser(traitements)
    lignes_allergies, texte_allergies, severes = _allergies(allergies)
    lignes_mesures, nb_mesures, nb_types = _mesures(mesures, maintenant)
    lignes_demandes = _demandes(demandes)
    lignes_consultations = _consultations(consultations)

    blocs = [f"PROFIL : {_profil(age, sexe, groupe_sanguin)}."]
    blocs.append(f"ANTÉCÉDENTS (écrits par le patient) : {antecedents_texte or 'non renseignés'}")
    blocs.append(f"TRAITEMENTS EN COURS (écrits par le patient) : {traitements_texte or 'non renseignés'}")
    blocs.append("ALLERGIES :\n" + ("\n".join(lignes_allergies) if lignes_allergies else "aucune enregistrée"))
    blocs.append(
        f"MESURES DE SANTÉ (les {MESURES_PAR_TYPE} plus récentes de chaque type, sur six mois) :\n"
        + ("\n".join(lignes_mesures) if lignes_mesures else "aucune")
    )
    blocs.append(
        f"CONSULTATIONS PASSÉES (comptes rendus, les {MAX_CONSULTATIONS} plus récentes) :\n"
        + ("\n".join(lignes_consultations) if lignes_consultations else "aucune")
    )
    blocs.append(
        "DEMANDES DE RENDEZ-VOUS RÉCENTES (niveau d'urgence : 1 = vital, 5 = non urgent) :\n"
        + ("\n".join(lignes_demandes) if lignes_demandes else "aucune")
    )
    if manquants:
        blocs.append("INFORMATIONS ABSENTES DU DOSSIER : " + " ; ".join(m.lower() for m in manquants) + ".")

    lu = [
        ("Profil", _profil(age, sexe, groupe_sanguin), True),
        ("Antécédents", "texte lu" if antecedents_texte else "non renseignés", bool(antecedents_texte)),
        ("Traitements en cours", "texte lu" if traitements_texte else "non renseignés", bool(traitements_texte)),
        ("Allergies", (_pluriel(len(lignes_allergies), "allergie") + (f", dont {_pluriel(severes, 'sévère')}" if severes else ""))
         if lignes_allergies else "aucune enregistrée", bool(lignes_allergies)),
        ("Mesures de santé", f"{_pluriel(nb_mesures, 'mesure')} ({_pluriel(nb_types, 'type')})" if nb_mesures else "aucune sur six mois", bool(nb_mesures)),
        ("Consultations passées", _pluriel(len(lignes_consultations), "consultation") if lignes_consultations else "aucune", bool(lignes_consultations)),
        ("Demandes de rendez-vous", f"{_pluriel(len(lignes_demandes), 'demande')} récente{'s' if len(lignes_demandes) > 1 else ''}" if lignes_demandes else "aucune", bool(lignes_demandes)),
    ]
    return DossierIA(
        texte="\n".join(blocs),
        allergies=texte_allergies,
        lu=lu,
        a_du_contenu=bool(antecedents_texte or traitements_texte or lignes_allergies or nb_mesures or lignes_consultations or lignes_demandes or groupe_sanguin),
    )
