from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404

from . import medecins_test
from .forms import (
    DossierMedicalForm,
    InscriptionPatientForm,
    ProfilPatientForm,
    SymptomesForm,
)
from .models import (
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
    return render(request, "patients/medecins.html", {
        "medecins": medecins_test.filtrer(specialite, ville),
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
        return redirect("patients:resultat", pk=triage.pk)

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
        if t.pk != triage.pk:  # la demande ne passe pas devant elle-même
            files.setdefault(t.medecin_id, []).append(t.niveau_effectif)
    return choisir_alternatives(triage.niveau_effectif, courant, medecins_test.tous(), files)


@login_required
def resultat(request, pk):
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    return render(request, "patients/resultat.html", {
        "triage": triage,
        "message": MESSAGES_NIVEAU.get(triage.niveau_effectif, ""),
        "propositions": _propositions(triage),
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
def file_medecin_test(request, medecin_id):
    """Vue de TEST de la file d'un médecin (l'interface finale est celle du
    module `medecins`). Réservée au personnel et aux comptes médecin."""
    if not (request.user.is_staff or request.user.role == request.user.Role.MEDECIN):
        raise PermissionDenied("Réservé aux médecins.")
    medecin = medecins_test.trouver(medecin_id)
    if medecin is None:
        raise Http404("Médecin introuvable.")
    demandes = Triage.file_du_medecin(medecin_id)
    return render(request, "patients/file_medecin.html", {
        "medecin": medecin,
        "demandes": demandes,
        "medecins": medecins_test.tous(),
    })


@login_required
def tableau_de_bord(request):
    patient = _patient_connecte(request)
    triages = sorted(
        Triage.objects.filter(patient=patient), key=lambda t: t.cree_le, reverse=True
    )

    files = {}  # une seule lecture de la file par médecin
    en_attente = None  # chargé seulement si un cas très urgent le nécessite
    en_cours, historique = [], []
    for t in triages:
        if t.est_actif:
            if t.statut == Triage.Statut.EN_ATTENTE:
                if t.medecin_id not in files:
                    files[t.medecin_id] = Triage.file_du_medecin(t.medecin_id)
                t.place = t.place_dans_la_file(files[t.medecin_id])
            else:
                t.place = None
            t.propositions = []
            if t.statut == Triage.Statut.EN_ATTENTE and est_eligible(t.niveau_effectif):
                if en_attente is None:
                    en_attente = list(Triage.objects.filter(statut=Triage.Statut.EN_ATTENTE))
                t.propositions = _propositions(t, en_attente)
            en_cours.append(t)
        else:
            historique.append(t)

    return render(request, "patients/tableau_de_bord.html", {
        "patient": patient,
        "en_cours": en_cours,
        "historique": historique,
    })
