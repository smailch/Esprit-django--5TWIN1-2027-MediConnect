import csv
import datetime

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404

from . import dossier as synthese, medecins_test, mesures_stats, planning, suivi
from .forms import (
    AllergieForm,
    MesureForm,
    DossierMedicalForm,
    InscriptionPatientForm,
    ProfilPatientForm,
    SymptomesForm,
)
from .models import (
    Allergie,
    Mesure,
    AutoEvaluation,
    ConstantesVitales,
    DossierMedical,
    Patient,
    SymptomeDeclare,
    Triage,
)
from .suggestions import choisir_alternatives, est_eligible
from .triage import MESSAGES_NIVEAU, evaluer


def inscription(request):
    if request.user.is_authenticated:
        return redirect("patients:tableau_de_bord")

    form = InscriptionPatientForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Votre compte a bien été créé. Bienvenue sur MediConnect !")
        return redirect("patients:tableau_de_bord")
    return render(request, "patients/inscription.html", {"form": form})


@login_required
def profil(request):
    try:
        patient = request.user.patient
    except Patient.DoesNotExist:
        raise PermissionDenied("Cet espace est réservé aux patients.")
    dossier, _ = DossierMedical.objects.get_or_create(patient=patient)

    if request.method == "POST":
        profil_form = ProfilPatientForm(request.POST, instance=patient)
        dossier_form = DossierMedicalForm(request.POST, instance=dossier)
        if profil_form.is_valid() and dossier_form.is_valid():
            profil_form.save()
            dossier_form.save()
            messages.success(request, "Vos informations ont été enregistrées.")
            return redirect("patients:profil")
    else:
        profil_form = ProfilPatientForm(instance=patient)
        dossier_form = DossierMedicalForm(instance=dossier)

    return render(
        request,
        "patients/profil.html",
        {"patient": patient, "profil_form": profil_form, "dossier_form": dossier_form},
    )


# --- Demande de rendez-vous : choix du médecin, symptômes, triage -----------

def _patient_connecte(request):
    try:
        return request.user.patient
    except Patient.DoesNotExist:
        raise PermissionDenied("Cet espace est réservé aux patients.")


@login_required
def liste_medecins(request):
    _patient_connecte(request)
    specialite = request.GET.get("specialite", "")
    ville = request.GET.get("ville", "")
    en_attente = suivi.toutes_les_demandes_en_attente()
    maintenant = timezone.localtime()
    medecins = []
    for m in medecins_test.filtrer(specialite, ville):
        pris = [t.creneau for t in en_attente if t.medecin_id == m["id"] and t.creneau]
        libres = planning.generer(m.get("horaires", {}) if m["disponible"] else {}, maintenant, pris)
        medecins.append(dict(
            m,
            prochain_creneau=libres[0] if libres else None,
            en_attente=sum(1 for t in en_attente if t.medecin_id == m["id"] and not t.creneau),
        ))
    return render(request, "patients/medecins.html", {
        "medecins": medecins,
        "specialites": medecins_test.specialites(),
        "villes": medecins_test.villes(),
        "specialite": specialite,
        "ville": ville,
    })


@login_required
def declarer_symptomes(request, medecin_id):
    patient = _patient_connecte(request)
    medecin = medecins_test.trouver(medecin_id)
    if medecin is None:
        raise Http404("Médecin introuvable.")

    form = SymptomesForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        choisis = form.cleaned_data["symptomes"]
        symptomes = [
            {
                "nom": sy.nom,
                "poids": sy.poids,
                "drapeau_rouge": sy.drapeau_rouge,
                "niveau_minimal": sy.niveau_minimal,
            }
            for sy in choisis
        ]
        constantes = form.constantes()
        auto_evaluation = form.auto_evaluation()
        resultat = evaluer(symptomes, constantes, auto_evaluation)
        triage = Triage.objects.create(
            patient=patient,
            medecin_id=medecin["id"],
            medecin_nom=medecin["nom"],
            medecin_specialite=medecin["specialite"],
            symptomes=[
                SymptomeDeclare(nom=d["nom"], poids=d["poids"], drapeau_rouge=d["drapeau_rouge"])
                for d in symptomes
            ],
            constantes=ConstantesVitales(**constantes) if constantes else None,
            auto_evaluation=AutoEvaluation(**auto_evaluation),
            texte_libre=form.cleaned_data["texte_libre"],
            score=resultat.score,
            niveau=resultat.niveau,
            explication=resultat.explication,
            drapeaux_rouges=resultat.drapeaux_rouges,
        )
        if planning.reservable(triage.statut, triage.niveau_effectif):
            return redirect("patients:creneaux", pk=triage.pk)  # étape 3 : choisir le jour et l'heure
        return redirect("patients:resultat", pk=triage.pk)  # cas prioritaire : pas de créneau à choisir

    return render(request, "patients/symptomes.html", {"form": form, "medecin": medecin})


def _propositions(triage, en_attente=None):
    """Médecins disponibles proposés à un patient très urgent (niveau 1 ou 2).

    `en_attente` permet de réutiliser les demandes déjà chargées (une seule
    requête pour plusieurs triages)."""
    if triage.statut != Triage.Statut.EN_ATTENTE or not est_eligible(triage.niveau_effectif):
        return []
    courant = medecins_test.trouver(triage.medecin_id) or {
        "id": triage.medecin_id,
        "nom": triage.medecin_nom,
        "specialite": triage.medecin_specialite,
        "ville": "",
        "disponible": False,
    }
    if en_attente is None:
        en_attente = Triage.objects.filter(statut=Triage.Statut.EN_ATTENTE)
    files = {}
    for t in en_attente:
        if t.pk != triage.pk and not t.creneau:  # ni devant elle-même, ni les rendez-vous fixés
            files.setdefault(t.medecin_id, []).append(t.niveau_effectif)
    return choisir_alternatives(triage.niveau_effectif, courant, medecins_test.tous(), files)


@login_required
def resultat(request, pk):
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.statut == Triage.Statut.EN_ATTENTE:
        du_medecin = list(Triage.objects.filter(medecin_id=triage.medecin_id, statut=Triage.Statut.EN_ATTENTE))
        suivi.annoter(du_medecin)
        triage = next((t for t in du_medecin if t.pk == triage.pk), triage)
    return render(request, "patients/resultat.html", {
        "triage": triage,
        "message": MESSAGES_NIVEAU.get(triage.niveau_effectif, ""),
        "propositions": _propositions(triage),
        "can_book": planning.reservable(triage.statut, triage.niveau_effectif),
    })


@login_required
@require_POST
def annuler(request, pk):
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.statut == Triage.Statut.EN_ATTENTE:
        triage.statut = Triage.Statut.ANNULE
        triage.save(update_fields=["statut"])
        messages.success(request, "Votre demande a été annulée.")
    return redirect("patients:resultat", pk=triage.pk)


@login_required
@require_POST
def transferer(request, pk, medecin_id):
    """Le patient accepte la proposition : sa demande passe chez ce médecin."""
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    # Seuls les médecins réellement proposés sont acceptés.
    choisi = next((m for m in _propositions(triage) if m["id"] == medecin_id), None)
    if choisi is None:
        messages.error(request, "Ce médecin n'est plus proposé pour votre demande.")
        return redirect("patients:resultat", pk=triage.pk)
    triage.medecin_id = choisi["id"]
    triage.medecin_nom = choisi["nom"]
    triage.medecin_specialite = choisi["specialite"]
    triage.save(update_fields=["medecin_id", "medecin_nom", "medecin_specialite"])
    messages.success(request, f"Votre demande a été transmise à {choisi['nom']}.")
    return redirect("patients:resultat", pk=triage.pk)


@login_required
def creneaux(request, pk):
    """Choix (ou changement) du créneau de rendez-vous d'une demande de niveau 3 à 5."""
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if not planning.reservable(triage.statut, triage.niveau_effectif):
        messages.error(request, "Un créneau ne peut pas être choisi pour cette demande.")
        return redirect("patients:resultat", pk=triage.pk)

    medecin = medecins_test.trouver(triage.medecin_id)
    horaires = medecin.get("horaires", {}) if medecin and medecin.get("disponible") else {}
    maintenant = timezone.localtime()

    def libres():
        pris = Triage.creneaux_pris(triage.medecin_id, exclure_pk=triage.pk)
        return planning.generer(horaires, maintenant, pris), pris

    disponibles, pris = libres()
    if request.method == "POST":
        choix = planning.lire_choix(request.POST.get("debut", ""), maintenant.tzinfo)
        if choix is None or choix not in disponibles:
            messages.error(request, "Ce créneau n'est plus disponible. Choisissez-en un autre.")
        elif any(t.creneau == choix for t in _demandes_actives(patient) if t.pk != triage.pk):
            messages.error(request, "Vous avez déjà un rendez-vous à cette heure-là.")
        else:
            ancien = triage.creneau
            triage.creneau = choix
            triage.save(update_fields=["creneau"])
            # Second verrou : si un autre patient a réservé le même créneau à la même seconde, on annule.
            if choix in Triage.creneaux_pris(triage.medecin_id, exclure_pk=triage.pk):
                triage.creneau = ancien
                triage.save(update_fields=["creneau"])
                messages.error(request, "Ce créneau vient d'être pris par un autre patient. Choisissez-en un autre.")
            else:
                messages.success(request, "Votre créneau est réservé.")
                return redirect("patients:resultat", pk=triage.pk)
        disponibles, pris = libres()  # le créneau a pu être pris entre-temps : liste à jour

    return render(request, "patients/creneaux.html", {
        "triage": triage,
        "medecin": medecin,
        "jours": planning.grouper_grille(planning.grille(horaires, maintenant, pris)),
        "total": len(disponibles),
        "duree": planning.DUREE_MINUTES,
    })


def _demandes_actives(patient):
    actives = [Triage.Statut.EN_ATTENTE, Triage.Statut.EN_CONSULTATION]
    return list(Triage.objects.filter(patient=patient, statut__in=actives))


@login_required
@require_POST
def creneau_retirer(request, pk):
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.creneau and triage.statut == Triage.Statut.EN_ATTENTE:
        triage.creneau = None
        triage.save(update_fields=["creneau"])
        messages.success(request, "Votre créneau a été libéré. Vous restez dans la file du médecin.")
    return redirect("patients:resultat", pk=triage.pk)


@login_required
def file_medecin_test(request, medecin_id):
    """Vue de TEST de la file d'un médecin (l'interface finale est celle du
    module `medecins`). Réservée au personnel et aux comptes médecin."""
    if not (request.user.is_staff or request.user.role == request.user.Role.MEDECIN):
        raise PermissionDenied("Réservé aux médecins.")
    medecin = medecins_test.trouver(medecin_id)
    if medecin is None:
        raise Http404("Médecin introuvable.")
    du_medecin = list(Triage.objects.filter(medecin_id=medecin_id, statut=Triage.Statut.EN_ATTENTE))
    groupes = suivi.annoter(du_medecin).get(medecin_id, {"file": [], "planning": []})
    return render(request, "patients/file_medecin.html", {
        "medecin": medecin,
        "demandes": groupes["file"],
        "planning": groupes["planning"],
        "medecins": medecins_test.tous(),
    })


@login_required
def tableau_de_bord(request):
    patient = _patient_connecte(request)
    triages = sorted(
        Triage.objects.filter(patient=patient), key=lambda t: t.cree_le, reverse=True
    )

    # Une seule lecture de toutes les demandes en attente : la place d'un patient dépend des autres.
    en_attente = suivi.toutes_les_demandes_en_attente()
    suivi.annoter(en_attente)
    annotees = {t.pk: t for t in en_attente}

    en_cours, historique = [], []
    for t in triages:
        t = annotees.get(t.pk, t)
        if t.est_actif:
            if t.statut != Triage.Statut.EN_ATTENTE:
                t.place, t.delai, t.prise_en_charge_estimee, t.protegee = None, None, None, False
            t.propositions = []
            t.peut_reserver = planning.reservable(t.statut, t.niveau_effectif) and not t.creneau
            if t.statut == Triage.Statut.EN_ATTENTE and est_eligible(t.niveau_effectif):
                t.propositions = _propositions(t, en_attente)
            en_cours.append(t)
        else:
            historique.append(t)

    return render(request, "patients/tableau_de_bord.html", {
        "patient": patient,
        "en_cours": en_cours,
        "historique": historique,
    })


# --- Allergies : liste, ajout, modification, suppression -------------------------------

_ORDRE_GRAVITE = {Allergie.Gravite.SEVERE: 0, Allergie.Gravite.MODEREE: 1, Allergie.Gravite.LEGERE: 2}


@login_required
def allergies(request):
    patient = _patient_connecte(request)
    toutes = list(Allergie.objects.filter(patient=patient))
    actives = sorted((a for a in toutes if a.active), key=lambda a: (_ORDRE_GRAVITE[a.gravite], a.substance.lower()))
    inactives = sorted((a for a in toutes if not a.active), key=lambda a: a.substance.lower())
    return render(request, "patients/allergies.html", {
        "actives": actives,
        "inactives": inactives,
        "severes": [a for a in actives if a.est_severe],
    })


@login_required
def allergie_creer(request):
    patient = _patient_connecte(request)
    form = AllergieForm(request.POST if request.method == "POST" else None, patient=patient)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "L'allergie a été ajoutée à votre dossier.")
        return redirect("patients:allergies")
    return render(request, "patients/allergie_form.html", {"form": form, "allergie": None})


@login_required
def allergie_modifier(request, pk):
    patient = _patient_connecte(request)
    allergie = objet_ou_404(Allergie, pk=pk, patient=patient)
    form = AllergieForm(request.POST if request.method == "POST" else None, instance=allergie, patient=patient)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "L'allergie a été mise à jour.")
        return redirect("patients:allergies")
    return render(request, "patients/allergie_form.html", {"form": form, "allergie": allergie})


@login_required
def allergie_supprimer(request, pk):
    """GET : demande de confirmation ; POST : suppression."""
    patient = _patient_connecte(request)
    allergie = objet_ou_404(Allergie, pk=pk, patient=patient)
    if request.method == "POST":
        nom = allergie.substance
        allergie.delete()
        messages.success(request, f"L'allergie « {nom} » a été supprimée.")
        return redirect("patients:allergies")
    return render(request, "patients/allergie_supprimer.html", {"allergie": allergie})


# --- Mesures de santé : historique, ajout, modification, suppression ---------------------

PERIODES = (("30", "30 jours"), ("90", "90 jours"), ("tout", "Tout"))


def _mesures_filtrees(request, patient):
    """Mesures du patient, de la plus récente à la plus ancienne, selon ?type= et ?periode=."""
    type_choisi = request.GET.get("type", "")
    if type_choisi not in Mesure.REGLES:
        type_choisi = ""
    periode = request.GET.get("periode", "tout")
    if periode not in dict(PERIODES):
        periode = "tout"
    mesures_patient = sorted(Mesure.objects.filter(patient=patient), key=lambda m: m.mesure_le, reverse=True)
    liste = [m for m in mesures_patient if not type_choisi or m.type == type_choisi]
    if periode != "tout":
        debut = timezone.now() - datetime.timedelta(days=int(periode))
        liste = [m for m in liste if m.mesure_le >= debut]
    return mesures_patient, liste, type_choisi, periode


@login_required
def mesures(request):
    patient = _patient_connecte(request)
    toutes, historique, type_choisi, periode = _mesures_filtrees(request, patient)
    dernieres = []
    for code, libelle in Mesure.Type.choices:
        derniere = next((m for m in toutes if m.type == code), None)
        dernieres.append({"code": code, "libelle": libelle, "mesure": derniere})

    resume = graphique = resume2 = None
    if type_choisi:
        chrono = list(reversed(historique))
        resume = mesures_stats.resume([m.valeur for m in chrono])
        if type_choisi == Mesure.Type.TENSION:
            resume2 = mesures_stats.resume([m.valeur2 for m in chrono if m.valeur2 is not None])
        bas, haut = Mesure.REGLES[type_choisi][3:]
        graphique = mesures_stats.graphique([(m.mesure_le, m.valeur, m.valeur2) for m in chrono], bas, haut)
    return render(request, "patients/mesures.html", {
        "dernieres": dernieres,
        "historique": historique[:100],
        "total": len(historique),
        "types": Mesure.Type.choices,
        "type_choisi": type_choisi,
        "periodes": PERIODES,
        "periode": periode,
        "resume": resume,
        "resume2": resume2,
        "unite": Mesure.REGLES[type_choisi][0] if type_choisi else "",
        "graphique": graphique,
    })


def _protege_tableur(texte):
    """Un texte qui commence par = + - @ serait exécuté comme une formule par un tableur."""
    return "'" + texte if texte[:1] in ("=", "+", "-", "@") else texte


@login_required
def mesures_exporter(request):
    """Télécharge l'historique (selon les filtres en cours) au format CSV, lisible dans Excel."""
    patient = _patient_connecte(request)
    _, historique, _, _ = _mesures_filtrees(request, patient)
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = 'attachment; filename="mes-mesures-de-sante.csv"'
    reponse.write("\ufeff")  # signature UTF-8 : Excel affiche bien les accents
    ecrivain = csv.writer(reponse, delimiter=";")
    ecrivain.writerow(["Type", "Valeur", "Second chiffre (tension)", "Unité", "Date et heure", "Remarque"])
    for m in reversed(historique):
        ecrivain.writerow([
            m.get_type_display(), f"{m.valeur:g}", "" if m.valeur2 is None else f"{m.valeur2:g}", m.unite,
            timezone.localtime(m.mesure_le).strftime("%d/%m/%Y %H:%M"), _protege_tableur(m.note),
        ])
    return reponse


@login_required
def mesure_creer(request):
    patient = _patient_connecte(request)
    form = MesureForm(request.POST if request.method == "POST" else None, patient=patient)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "La mesure a été enregistrée.")
        return redirect("patients:mesures")
    return render(request, "patients/mesure_form.html", {"form": form, "mesure": None, "regles": _regles()})


@login_required
def mesure_modifier(request, pk):
    patient = _patient_connecte(request)
    mesure = objet_ou_404(Mesure, pk=pk, patient=patient)
    form = MesureForm(request.POST if request.method == "POST" else None, instance=mesure, patient=patient)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "La mesure a été mise à jour.")
        return redirect("patients:mesures")
    return render(request, "patients/mesure_form.html", {"form": form, "mesure": mesure, "regles": _regles()})


@login_required
def mesure_supprimer(request, pk):
    """GET : demande de confirmation ; POST : suppression."""
    patient = _patient_connecte(request)
    mesure = objet_ou_404(Mesure, pk=pk, patient=patient)
    if request.method == "POST":
        mesure.delete()
        messages.success(request, "La mesure a été supprimée.")
        return redirect("patients:mesures")
    return render(request, "patients/mesure_supprimer.html", {"mesure": mesure})


def _regles():
    """Unité et bornes de chaque type, pour afficher l'unité dès le choix du type."""
    return {code: {"unite": r[0], "min": r[1], "max": r[2]} for code, r in Mesure.REGLES.items()}


# --- Dossier médical : la synthèse lue par le médecin avant la consultation ----------------

@login_required
def dossier(request):
    patient = _patient_connecte(request)
    fiche = DossierMedical.objects.filter(patient=patient).first()
    toutes = list(Allergie.objects.filter(patient=patient))
    actives = sorted((a for a in toutes if a.active), key=lambda a: (_ORDRE_GRAVITE[a.gravite], a.substance.lower()))
    demandes = sorted(Triage.objects.filter(patient=patient), key=lambda t: t.cree_le, reverse=True)
    mesures_recentes = synthese.derniere_mesure_par_type(Mesure.objects.filter(patient=patient))
    ordre_types = [code for code, _ in Mesure.Type.choices]
    mesures_recentes.sort(key=lambda m: ordre_types.index(m.type))
    return render(request, "patients/dossier.html", {
        "patient": patient,
        "dossier": fiche,
        "allergies": actives,
        "severes": [a for a in actives if a.est_severe],
        "mesures": mesures_recentes,
        "derniere_demande": demandes[0] if demandes else None,
        "manquants": synthese.elements_manquants(patient, fiche),
    })
