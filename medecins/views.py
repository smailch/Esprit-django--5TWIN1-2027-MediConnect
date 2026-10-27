from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404
from patients import dossier as synthese_dossier
from patients import suivi
from patients import visio as salle_visio
from patients.models import Consultation, DossierMedical, Triage

from . import agenda
from .forms import CompteRenduForm, InscriptionMedecinForm, ProfilMedecinForm, RequalificationForm, consultation_pour
from .models import Medecin
from .courriel import EchecEnvoi as EchecCourriel
from .courriel import contexte_envoi as contexte_courriel
from .courriel import envoyer_compte_rendu as envoyer_courriel
from .sms import EchecEnvoi, envoyer_compte_rendu
from .whatsapp import EchecEnvoi as EchecWhatsApp
from .whatsapp import contexte_envoi as contexte_whatsapp
from .whatsapp import envoyer_compte_rendu as envoyer_whatsapp
from .whatsapp import notifier_lancement
from .whatsapp import numero_expediteur_affiche


def _medecin_requis(actif=True):
    """Réserve la vue aux comptes médecin. `actif=False` laisse passer un compte pas encore validé."""

    def decorateur(vue):
        @login_required
        @wraps(vue)
        def interne(request, *args, **kwargs):
            utilisateur = request.user
            if getattr(utilisateur, "role", None) != utilisateur.Role.MEDECIN:
                raise PermissionDenied("Cet espace est réservé aux médecins.")
            try:
                medecin = utilisateur.medecin
            except Medecin.DoesNotExist:
                raise PermissionDenied("Aucun profil médecin n'est associé à ce compte.")
            if actif and not utilisateur.est_valide:
                return redirect("medecins:en_attente")
            request.medecin = medecin
            return vue(request, *args, **kwargs)

        return interne

    return decorateur


def _triage_du_medecin(medecin, pk):
    return objet_ou_404(Triage, pk=pk, medecin_id=medecin.code)


def inscription(request):
    if request.user.is_authenticated:
        if getattr(request.user, "role", None) == request.user.Role.MEDECIN:
            return redirect("medecins:tableau_de_bord")
        return redirect("home")
    form = InscriptionMedecinForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        utilisateur = form.save()
        login(request, utilisateur)
        messages.success(
            request,
            "Votre compte a été créé. Un administrateur doit le valider avant l'ouverture de votre file.",
        )
        return redirect("medecins:en_attente")
    return render(request, "medecins/inscription.html", {"form": form})


@_medecin_requis(actif=False)
def en_attente(request):
    if request.user.est_valide:
        return redirect("medecins:tableau_de_bord")
    return render(request, "medecins/en_attente.html", {"medecin": request.medecin})


@_medecin_requis()
def tableau_de_bord(request):
    medecin = request.medecin
    demandes = list(Triage.objects.filter(medecin_id=medecin.code, statut=Triage.Statut.EN_ATTENTE))
    groupes = suivi.annoter(demandes).get(medecin.code, {"file": [], "planning": []})
    en_consultation = list(
        Triage.objects.filter(medecin_id=medecin.code, statut=Triage.Statut.EN_CONSULTATION)
    )
    jours = agenda.par_jour(groupes["file"], groupes["planning"])
    return render(request, "medecins/tableau_de_bord.html", {
        "medecin": medecin,
        "file": groupes["file"],
        "agenda": jours,
        "agenda_total": sum(len(jour["evenements"]) for jour in jours),
        "en_consultation": en_consultation,
    })


def _contexte_synthese(triage):
    patient = triage.patient
    try:
        dossier = patient.dossier
    except DossierMedical.DoesNotExist:
        dossier = None
    return {
        "triage": triage,
        "patient": patient,
        "dossier": dossier,
        "allergies": list(patient.allergies.all()),
        "mesures": synthese_dossier.derniere_mesure_par_type(list(patient.mesures.all())),
        "manquants": synthese_dossier.elements_manquants(patient, dossier),
        "consultation": Consultation.objects.filter(triage=triage).first(),
    }


@_medecin_requis()
def synthese(request, pk):
    triage = _triage_du_medecin(request.medecin, pk)
    contexte = _contexte_synthese(triage)
    contexte["form_niveau"] = RequalificationForm(initial={"niveau": triage.niveau_effectif or triage.niveau})
    return render(request, "medecins/synthese.html", contexte)


@_medecin_requis()
@require_POST
def requalifier(request, pk):
    triage = _triage_du_medecin(request.medecin, pk)
    if not triage.est_actif:
        raise PermissionDenied("Cette demande est déjà close.")
    form = RequalificationForm(request.POST)
    if form.is_valid():
        triage.niveau_medecin = form.cleaned_data["niveau"]
        triage.save(update_fields=["niveau_medecin"])
        messages.success(request, "Le niveau d'urgence a été requalifié. C'est ce niveau qui fait foi.")
    else:
        messages.error(request, "Le niveau indiqué n'est pas valable.")
    return redirect("medecins:synthese", pk=triage.pk)


@_medecin_requis()
@require_POST
def commencer(request, pk):
    triage = _triage_du_medecin(request.medecin, pk)
    if triage.statut == Triage.Statut.EN_ATTENTE:
        triage.enregistrer_depassements()
        triage.statut = Triage.Statut.EN_CONSULTATION
        triage.save(update_fields=["statut"])
        try:
            envoi = notifier_lancement(triage, request.medecin.nom_affiche)
        except EchecWhatsApp as erreur:
            messages.warning(
                request,
                f"Consultation commencée. Le patient est sorti de la file. WhatsApp : {erreur}",
            )
        else:
            messages.success(
                request,
                f"Consultation commencée. Un WhatsApp a été envoyé au {envoi['affichage']}.",
            )
    elif triage.statut != Triage.Statut.EN_CONSULTATION:
        raise PermissionDenied("Cette demande ne peut plus être ouverte.")
    return redirect("medecins:visio", pk=triage.pk)


@_medecin_requis()
def visio(request, pk):
    triage = _triage_du_medecin(request.medecin, pk)
    if triage.statut not in (Triage.Statut.EN_ATTENTE, Triage.Statut.EN_CONSULTATION):
        messages.info(request, "La téléconsultation est terminée. Le compte rendu reste consultable.")
        return redirect("medecins:synthese", pk=triage.pk)
    return render(request, "medecins/visio.html", {
        "triage": triage,
        "jitsi": salle_visio.config(triage, request.medecin.nom_affiche),
    })


@_medecin_requis()
def compte_rendu(request, pk):
    medecin = request.medecin
    triage = _triage_du_medecin(medecin, pk)
    if triage.statut == Triage.Statut.ANNULE:
        raise PermissionDenied("Une demande annulée n'a pas de compte rendu.")
    consultation = consultation_pour(triage, medecin)
    form = CompteRenduForm(request.POST if request.method == "POST" else None, instance=consultation)
    if request.method == "POST" and form.is_valid():
        if triage.statut == Triage.Statut.EN_ATTENTE:
            triage.enregistrer_depassements()
        objet = form.save(commit=False)
        objet.patient = triage.patient
        objet.triage = triage
        objet.medecin_nom = medecin.nom_affiche
        objet.medecin_specialite = medecin.specialite
        objet.save()
        form.enregistrer_actes(objet)
        if triage.statut != Triage.Statut.TERMINE:
            triage.statut = Triage.Statut.TERMINE
            triage.save(update_fields=["statut"])
        messages.success(request, "Le compte rendu est enregistré dans le dossier du patient.")
        return redirect("medecins:consultation_detail", pk=objet.pk)
    return render(request, "medecins/compte_rendu.html", {
        "form": form,
        "triage": triage,
        "consultation": consultation,
        **_envoi_whatsapp(consultation),
    })


@_medecin_requis()
def consultations(request):
    liste = Consultation.objects.filter(triage__medecin_id=request.medecin.code)
    return render(request, "medecins/consultations.html", {"consultations": liste, "medecin": request.medecin})


def _consultation_du_medecin(medecin, pk):
    return objet_ou_404(Consultation, pk=pk, triage__medecin_id=medecin.code)


def _envoi_whatsapp(consultation):
    return {**contexte_whatsapp(consultation), **contexte_courriel(consultation)}


@_medecin_requis()
@require_POST
def envoyer_sms(request, pk):
    """Le médecin clique : le compte rendu part par SMS vers le patient (numéro d'essai s'il est défini)."""
    consultation = _consultation_du_medecin(request.medecin, pk)
    try:
        resultat = envoyer_compte_rendu(consultation, getattr(request.medecin, "telephone", ""))
    except EchecEnvoi as erreur:
        messages.error(request, str(erreur))
        return redirect("medecins:consultation_detail", pk=consultation.pk)
    if resultat["mode"] == "api":
        messages.success(request, f"Le compte rendu a été envoyé par SMS au {resultat['affichage']}.")
        return redirect("medecins:consultation_detail", pk=consultation.pk)
    messages.info(
        request,
        f"L'application SMS s'ouvre pour le {resultat['affichage']}. Confirmez l'envoi. "
        "L'envoi sans cette confirmation demande un compte Twilio.",
    )
    return redirect(resultat["lien"])


@_medecin_requis()
@require_POST
def envoyer_whatsapp_vue(request, pk):
    """Le médecin clique : le compte rendu part par WhatsApp vers le patient."""
    consultation = _consultation_du_medecin(request.medecin, pk)
    try:
        resultat = envoyer_whatsapp(consultation, getattr(request.medecin, "telephone", ""))
    except EchecWhatsApp as erreur:
        messages.error(request, str(erreur))
        return redirect("medecins:consultation_detail", pk=consultation.pk)
    expediteur = numero_expediteur_affiche() or "+1 555 149 1710"
    messages.success(
        request,
        f"WhatsApp a accepté le compte rendu pour le {resultat['affichage']}. "
        f"Ouvrez la discussion avec {expediteur}. "
        "S'il n'y est pas, répondez « bonjour » dans cette discussion, puis cliquez à nouveau.",
    )
    return redirect("medecins:consultation_detail", pk=consultation.pk)


@_medecin_requis()
@require_POST
def envoyer_courriel_vue(request, pk):
    """Le médecin clique : le compte rendu PDF part vers l'e-mail du patient."""
    consultation = _consultation_du_medecin(request.medecin, pk)
    try:
        resultat = envoyer_courriel(consultation)
    except EchecCourriel as erreur:
        messages.error(request, str(erreur))
        return redirect("medecins:consultation_detail", pk=consultation.pk)
    messages.success(request, f"Le compte rendu PDF a été envoyé à {resultat['email']}.")
    return redirect("medecins:consultation_detail", pk=consultation.pk)


@_medecin_requis()
def consultation_detail(request, pk):
    consultation = _consultation_du_medecin(request.medecin, pk)
    return render(request, "medecins/consultation_detail.html", {
        "consultation": consultation,
        "actes": list(consultation.actes.all()),
        **_envoi_whatsapp(consultation),
    })


@_medecin_requis()
def consultation_modifier(request, pk):
    consultation = _consultation_du_medecin(request.medecin, pk)
    form = CompteRenduForm(request.POST if request.method == "POST" else None, instance=consultation)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Le compte rendu a été mis à jour.")
        return redirect("medecins:consultation_detail", pk=consultation.pk)
    return render(request, "medecins/compte_rendu.html", {
        "form": form,
        "triage": consultation.triage,
        "consultation": consultation,
        **_envoi_whatsapp(consultation),
    })


@_medecin_requis()
def consultation_supprimer(request, pk):
    consultation = _consultation_du_medecin(request.medecin, pk)
    if request.method == "POST":
        triage = consultation.triage
        consultation.delete()
        messages.success(request, "Le compte rendu a été supprimé. La demande reste marquée comme terminée.")
        return redirect("medecins:synthese", pk=triage.pk)
    return render(request, "medecins/consultation_supprimer.html", {"consultation": consultation})


@_medecin_requis(actif=False)
def profil(request):
    medecin = request.medecin
    form = ProfilMedecinForm(request.POST if request.method == "POST" else None, instance=medecin)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votre profil a été enregistré.")
        return redirect("medecins:profil")
    return render(request, "medecins/profil.html", {"form": form, "medecin": medecin})
