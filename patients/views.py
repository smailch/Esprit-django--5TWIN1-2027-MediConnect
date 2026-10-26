import csv
import datetime

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404, proteger_tableur
from ia import decision as decision_ia, modele as modele_ia, specialite as specialite_ia

from medecins import annuaire

from . import analyse_service, compte as gestion_compte, dossier as synthese, ia_client, ia_taches, mesures_stats, notifications, planning, suivi, taches, visio as salle_visio
from .forms import (
    OrientationForm,
    AllergieForm,
    CompteForm,
    FermetureCompteForm,
    MesureForm,
    DossierMedicalForm,
    InscriptionPatientForm,
    ProfilPatientForm,
    SuppressionCompteForm,
    SymptomesForm,
)
from .models import (
    Allergie,
    Mesure,
    AutoEvaluation,
    ConstantesVitales,
    Consultation,
    DossierMedical,
    Patient,
    ReglageTriage,
    Symptome,
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


# --- Mon compte : identité, mot de passe, données, fermeture ----------------------------

@login_required
def compte(request):
    """Identité du compte, accès au changement de mot de passe, export des données, désactivation et suppression."""
    patient = _patient_connecte(request)
    user = request.user
    ferme_possible = gestion_compte.peut_etre_ferme(user)
    identite = CompteForm(instance=user)
    fermer = FermetureCompteForm(user=user, prefix="fermer")
    supprimer = SuppressionCompteForm(user=user, prefix="supprimer")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "identite":
            identite = CompteForm(request.POST, instance=user)
            if identite.is_valid():
                identite.save()
                messages.success(request, "Votre identité a été mise à jour.")
                return redirect("patients:compte")
        elif action in ("desactiver", "supprimer") and not ferme_possible:
            messages.error(request, "Ce compte appartient au personnel : il ne peut pas être fermé depuis l'espace patient.")
            return redirect("patients:compte")
        elif action == "desactiver":
            fermer = FermetureCompteForm(request.POST, user=user, prefix="fermer")
            if fermer.is_valid():
                annulees = gestion_compte.desactiver(user)
                logout(request)
                messages.success(
                    request,
                    "Votre compte est désactivé." + (f" {annulees} demande(s) en attente ont été annulée(s)." if annulees else "")
                    + " Pour le réactiver, contactez un administrateur.",
                )
                return redirect("home")
        elif action == "supprimer":
            supprimer = SuppressionCompteForm(request.POST, user=user, prefix="supprimer")
            if supprimer.is_valid():
                logout(request)
                gestion_compte.supprimer(user)
                messages.success(request, "Votre compte et toutes vos données ont été supprimés définitivement.")
                return redirect("home")

    return render(request, "patients/compte.html", {
        "patient": patient, "identite": identite, "fermer": fermer, "supprimer": supprimer, "ferme_possible": ferme_possible,
    })


@login_required
def compte_exporter(request):
    """Télécharge toutes les données du patient au format JSON."""
    patient = _patient_connecte(request)
    reponse = JsonResponse(gestion_compte.donnees_patient(patient), json_dumps_params={"ensure_ascii": False, "indent": 2})
    reponse["Content-Disposition"] = 'attachment; filename="mes-donnees-mediconnect.json"'
    return reponse


# --- Demande de rendez-vous : choix du médecin, symptômes, triage -----------

def _patient_connecte(request):
    try:
        return request.user.patient
    except Patient.DoesNotExist:
        raise PermissionDenied("Cet espace est réservé aux patients.")


def _medecins_avec_disponibilite(medecins):
    """Les médecins donnés, chacun avec son prochain créneau libre et le nombre de patients en attente."""
    en_attente = suivi.toutes_les_demandes_en_attente()
    maintenant = timezone.localtime()
    resultat = []
    for m in medecins:
        pris = [t.creneau for t in en_attente if t.medecin_id == m["id"] and t.creneau]
        libres = planning.generer(m.get("horaires", {}) if m["disponible"] else {}, maintenant, pris)
        resultat.append(dict(
            m,
            prochain_creneau=libres[0] if libres else None,
            en_attente=sum(1 for t in en_attente if t.medecin_id == m["id"] and not t.creneau),
        ))
    return resultat


def _orienter(texte):
    """Ce que dit « Quel médecin consulter ? » d'un texte : urgence, spécialité conseillée et médecins disponibles.
    Rien n'est enregistré."""
    lecture = modele_ia.predire(texte)
    urgence = bool(lecture and lecture["niveau"] <= 2 and lecture["confiance"] >= decision_ia.SEUIL_PAR_DEFAUT)
    prediction = specialite_ia.predire(texte)
    conseillee, sure = specialite_ia.conseiller(prediction)
    medecins = _medecins_avec_disponibilite(annuaire.filtrer(conseillee, ""))
    repli = not any(m["disponible"] for m in medecins) and conseillee != specialite_ia.ls.MEDECINE_GENERALE
    if repli:  # aucun médecin de cette spécialité n'est disponible : la médecine générale reste un bon point de départ
        generalistes = _medecins_avec_disponibilite(annuaire.filtrer(specialite_ia.ls.MEDECINE_GENERALE, ""))
    else:
        generalistes = []
    return {
        "urgence": urgence,
        "specialite": conseillee,
        "sure": sure,
        "domaine": specialite_ia.ls.DOMAINES.get(conseillee, ""),
        "mots": (prediction or {}).get("mots", []) if sure else [],
        "medecins": medecins,
        "repli": repli,
        "generalistes": generalistes,
    }


@login_required
def orientation(request):
    """« Quel médecin consulter ? » : le patient décrit ce qu'il ressent, le site propose une spécialité et ses médecins."""
    _patient_connecte(request)
    form = OrientationForm(request.POST if request.method == "POST" else None)
    resultat = _orienter(form.cleaned_data["texte"]) if request.method == "POST" and form.is_valid() else None
    return render(request, "patients/orientation.html", {"form": form, "resultat": resultat})


@login_required
def liste_medecins(request):
    _patient_connecte(request)
    specialite = request.GET.get("specialite", "")
    ville = request.GET.get("ville", "")
    return render(request, "patients/medecins.html", {
        "medecins": _medecins_avec_disponibilite(annuaire.filtrer(specialite, ville)),
        "specialites": annuaire.specialites(),
        "villes": annuaire.villes(),
        "specialite": specialite,
        "ville": ville,
    })


@login_required
def declarer_symptomes(request, medecin_id):
    patient = _patient_connecte(request)
    medecin = annuaire.trouver(medecin_id)
    if medecin is None:
        raise Http404("Médecin introuvable.")
    if not medecin["disponible"]:
        messages.error(request, "Ce médecin ne prend pas de rendez-vous pour le moment.")
        return redirect("patients:medecins")

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
        ia_statut, ia_signes = _symptomes_par_ia(patient, form.cleaned_data["texte_libre"], symptomes)
        resultat = evaluer(symptomes, constantes, auto_evaluation)
        lecture, niveau, releve = _lecture_du_texte(form.cleaned_data["texte_libre"], resultat.niveau)
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
            niveau=niveau,
            explication=resultat.explication + (decision_ia.phrase_explicative(lecture, niveau) if releve else "") + (
                " L'IA a repéré dans votre texte : " + ", ".join(s.split(" — ")[0] for s in ia_signes) + " (à confirmer par le médecin)."
                if ia_signes else ""
            ),
            drapeaux_rouges=resultat.drapeaux_rouges,
            ia_statut=ia_statut,
            ia_signes=ia_signes,
            modele_niveau=lecture["niveau"] if lecture else None,
            modele_confiance=lecture["confiance"] if lecture else None,
            modele_mots=lecture["mots"] if lecture else [],
            modele_releve=releve,
        )
        _prevenir_des_changements(request, triage.medecin_id)  # une urgence peut retarder les rendez-vous fixés
        if planning.reservable(triage.statut, triage.niveau_effectif):
            return redirect("patients:creneaux", pk=triage.pk)  # étape 3 : choisir le jour et l'heure
        _confirmer_la_file(request, triage)  # cas prioritaire : pas de créneau à choisir, sa place est dans la file
        return redirect("patients:resultat", pk=triage.pk)

    return render(request, "patients/symptomes.html", {
        "form": form, "medecin": medecin, "ia": ia_client.description(), "consentement_ia": patient.consentement_ia,
    })


def _prevenir_des_changements(request, *medecin_ids):
    """Après un événement qui bouge l'agenda d'un médecin : prévient les patients dont l'heure prévue a changé."""
    def lien(triage):
        return request.build_absolute_uri(reverse("patients:resultat", args=[triage.pk]))

    for medecin_id in set(medecin_ids):
        suivi.prevenir_des_changements(medecin_id, lien)


def _confirmer_la_file(request, triage):
    """Le patient reste dans la file : un e-mail lui donne sa place et son heure estimée (une seule fois)."""
    suivi.confirmer_la_file(triage, lambda t: request.build_absolute_uri(reverse("patients:resultat", args=[t.pk])))


def _lecture_du_texte(texte, niveau_regles):
    """Avis du modèle local sur le texte libre : (lecture ou None, niveau final, niveau relevé ?).

    Le modèle ne peut que RELEVER l'urgence, et seulement s'il est assez sûr de lui (seuil réglable). S'il est absent
    ou en panne, le triage continue avec ses règles."""
    lecture = modele_ia.predire(texte)
    if lecture is None:
        return None, niveau_regles, False
    niveau, releve = decision_ia.relever(niveau_regles, lecture, ReglageTriage.actuel().seuil_modele / 100)
    return lecture, niveau, releve


def _symptomes_par_ia(patient, texte, symptomes):
    """Complète `symptomes` (liste modifiée sur place) avec ceux que l'IA repère dans le texte libre.

    L'IA ne fait qu'AJOUTER des symptômes du catalogue, chacun cité dans le texte : les règles existantes les pèsent
    ensuite comme les autres, donc le niveau ne peut que monter. Renvoie (statut, ["nom — « extrait »", …])."""
    if not (texte or "").strip() or not ia_client.est_active():
        return "", []
    if not patient.consentement_ia:
        return "non_consentie", []
    catalogue = {s.nom: s for s in Symptome.objects.filter(actif=True)}
    sortie = ia_taches.detecter_symptomes(
        texte, list(catalogue), age=patient.age, sexe=patient.sexe, identifiant=str(patient.pk)
    )
    if not sortie.ok:
        return sortie.statut, []
    deja = {s["nom"] for s in symptomes}
    signes = []
    for nom, extrait in sortie.elements["symptomes"]:
        if nom in deja:
            continue
        sy = catalogue[nom]
        symptomes.append({"nom": sy.nom, "poids": sy.poids, "drapeau_rouge": sy.drapeau_rouge, "niveau_minimal": sy.niveau_minimal})
        signes.append(f"{nom} — « {extrait} »")
    return sortie.statut, signes


def _propositions(triage, en_attente=None):
    """Médecins disponibles proposés à un patient très urgent (niveau 1 ou 2).

    `en_attente` permet de réutiliser les demandes déjà chargées (une seule
    requête pour plusieurs triages)."""
    if triage.statut != Triage.Statut.EN_ATTENTE or not est_eligible(triage.niveau_effectif):
        return []
    courant = annuaire.trouver(triage.medecin_id) or {
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
    return choisir_alternatives(triage.niveau_effectif, courant, annuaire.tous(), files)


@login_required
def resultat(request, pk):
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.statut == Triage.Statut.EN_ATTENTE:
        du_medecin = list(Triage.objects.filter(medecin_id=triage.medecin_id, statut=Triage.Statut.EN_ATTENTE))
        suivi.annoter(du_medecin)
        triage = next((t for t in du_medecin if t.pk == triage.pk), triage)
    consultation = Consultation.objects.filter(triage=triage).first() if triage.statut == Triage.Statut.TERMINE else None
    return render(request, "patients/resultat.html", {
        "triage": triage,
        "consultation": consultation,
        "message": MESSAGES_NIVEAU.get(triage.niveau_effectif, ""),
        "propositions": _propositions(triage),
        "can_book": planning.reservable(triage.statut, triage.niveau_effectif),
    })


@login_required
def visio(request, pk):
    """Ouvre la salle Jitsi de cette demande, la même que celle du médecin."""
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.statut != Triage.Statut.EN_CONSULTATION:
        messages.info(request, "La téléconsultation s'ouvre quand le médecin la commence.")
        return redirect("patients:resultat", pk=triage.pk)
    return render(request, "patients/visio.html", {
        "triage": triage,
        "jitsi": salle_visio.config(triage, str(patient)),
    })


@login_required
@require_POST
def annuler(request, pk):
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.statut == Triage.Statut.EN_ATTENTE:
        triage.statut = Triage.Statut.ANNULE
        triage.save(update_fields=["statut"])
        notifications.rendez_vous_annule(triage, request.build_absolute_uri(reverse("patients:medecins")))
        _prevenir_des_changements(request, triage.medecin_id)  # les rendez-vous suivants peuvent avancer
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
    ancien_medecin = triage.medecin_id
    triage.medecin_id = choisi["id"]
    triage.medecin_nom = choisi["nom"]
    triage.medecin_specialite = choisi["specialite"]
    triage.save(update_fields=["medecin_id", "medecin_nom", "medecin_specialite"])
    _prevenir_des_changements(request, ancien_medecin, triage.medecin_id)
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

    medecin = annuaire.trouver(triage.medecin_id)
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
            triage.heure_annoncee = None  # nouvelle heure fixée : plus rien d'annoncé
            triage.save(update_fields=["creneau", "heure_annoncee"])
            # Second verrou : si un autre patient a réservé le même créneau à la même seconde, on annule.
            if choix in Triage.creneaux_pris(triage.medecin_id, exclure_pk=triage.pk):
                triage.creneau = ancien
                triage.save(update_fields=["creneau"])
                messages.error(request, "Ce créneau vient d'être pris par un autre patient. Choisissez-en un autre.")
            else:
                messages.success(request, "Votre créneau est réservé.")
                notifications.rendez_vous_fixe(
                    triage, request.build_absolute_uri(reverse("patients:resultat", args=[triage.pk])), modifie=ancien is not None
                )
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
        triage.heure_annoncee = None
        triage.save(update_fields=["creneau", "heure_annoncee"])
        messages.success(request, "Votre créneau a été libéré. Vous restez dans la file du médecin.")
        _confirmer_la_file(request, triage)
    return redirect("patients:resultat", pk=triage.pk)


@login_required
@require_POST
def rester_dans_la_file(request, pk):
    """« Passer » à l'étape du créneau : le patient choisit de rester dans la file du médecin."""
    patient = _patient_connecte(request)
    triage = objet_ou_404(Triage, pk=pk, patient=patient)
    if triage.statut == Triage.Statut.EN_ATTENTE and not triage.creneau:
        _confirmer_la_file(request, triage)
    return redirect("patients:resultat", pk=triage.pk)


@login_required
def file_medecin_test(request, medecin_id):
    """Vue de TEST de la file d'un médecin (l'interface finale est celle du
    module `medecins`). Réservée au personnel et aux comptes médecin."""
    if not (request.user.is_staff or request.user.role == request.user.Role.MEDECIN):
        raise PermissionDenied("Réservé aux médecins.")
    medecin = annuaire.trouver(medecin_id)
    if medecin is None:
        raise Http404("Médecin introuvable.")
    du_medecin = list(Triage.objects.filter(medecin_id=medecin_id, statut=Triage.Statut.EN_ATTENTE))
    groupes = suivi.annoter(du_medecin).get(medecin_id, {"file": [], "planning": []})
    return render(request, "patients/file_medecin.html", {
        "medecin": medecin,
        "demandes": groupes["file"],
        "planning": groupes["planning"],
        "medecins": annuaire.tous(),
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
            timezone.localtime(m.mesure_le).strftime("%d/%m/%Y %H:%M"), proteger_tableur(m.note),
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
    consultations = sorted(Consultation.objects.filter(patient=patient), key=lambda c: c.date, reverse=True)
    return render(request, "patients/dossier.html", {
        "patient": patient,
        "dossier": fiche,
        "allergies": actives,
        "severes": [a for a in actives if a.est_severe],
        "mesures": mesures_recentes,
        "derniere_demande": demandes[0] if demandes else None,
        "manquants": synthese.elements_manquants(patient, fiche),
        "analyse": analyse_service.analyser_patient(patient, ia=analyse_service.CACHE),
        "consultations": consultations[:3],
        "nb_consultations": len(consultations),
    })


@login_required
def consultations(request):
    """Historique complet : le compte rendu de chaque consultation terminée, du plus récent au plus ancien."""
    patient = _patient_connecte(request)
    liste = sorted(Consultation.objects.filter(patient=patient), key=lambda c: c.date, reverse=True)
    return render(request, "patients/consultations.html", {"consultations": liste})


# Où mène le bouton d'action d'une remarque de l'analyse.
_LIENS_ANALYSE = {
    "rdv": "patients:medecins",
    "completer": "patients:profil",
    "allergies": "patients:allergies",
    "mesures": "patients:mesures",
    "mesure_nouvelle": "patients:mesure_creer",
}


@login_required
def analyse(request):
    """Analyse automatique du dossier : ce que l'assistant a repéré, et pourquoi."""
    patient = _patient_connecte(request)
    # Avec Celery, l'IA relit le dossier en arrière-plan : la page s'affiche tout de suite (voir patients/taches.py).
    resultat, ia_en_cours = taches.analyse_avec_ia_differee(patient)
    liens = {cle: reverse(nom) for cle, nom in _LIENS_ANALYSE.items()}

    def avec_lien(points):
        return [{"point": p, "url": liens.get(p.action)} for p in points]

    return render(request, "patients/analyse_dossier.html", {
        "analyse": resultat,
        "ia_en_cours": ia_en_cours,
        "groupes": [
            ("Important", "important", avec_lien(resultat.importants)),
            ("À surveiller", "attention", avec_lien(resultat.attentions)),
            ("Pour compléter ou vérifier", "info", avec_lien(resultat.infos)),
        ],
    })


@login_required
def analyse_etat(request):
    """Suivi de l'analyse IA lancée en arrière-plan (interrogé par la page toutes les 2 s)."""
    patient = _patient_connecte(request)
    marque = taches.etat(patient.pk)
    return JsonResponse({"en_cours": marque.get("etat") == "en_cours", "statut": marque.get("statut", "")})


# --- IA : consentement du patient -------------------------------------------------------------------------

_RETOURS_IA = {"analyse": "patients:analyse_dossier", "symptomes": "patients:medecins", "dossier": "patients:dossier"}


@login_required
def ia_consentement(request):
    """Explique ce que l'IA lit et où, et permet au patient de l'activer ou de la désactiver (désactivée par défaut)."""
    patient = _patient_connecte(request)
    retour = _RETOURS_IA.get(request.POST.get("retour") or request.GET.get("retour"), "patients:dossier")
    if request.method == "POST":
        actif = request.POST.get("actif") == "1" and ia_client.est_active()
        patient.consentement_ia = actif
        patient.consentement_ia_le = timezone.now() if actif else None
        patient.save(update_fields=["consentement_ia", "consentement_ia_le"])
        messages.success(request, "L'analyse par IA est activée." if actif else "L'analyse par IA est désactivée.")
        return redirect(retour)
    return render(request, "patients/ia_consentement.html", {
        "ia": ia_client.description(), "patient": patient, "retour": request.GET.get("retour", "dossier"),
    })
