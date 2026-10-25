import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404, proteger_tableur
from ia import decision as decision_ia, modele as modele_ia
from patients import analyse_service, compte as gestion_compte, ia_client, medecins_test, notifications, suivi
from patients.models import (
    Allergie,
    Consultation,
    DossierMedical,
    Mesure,
    Patient,
    ReglageTriage,
    Symptome,
    Triage,
)

from .forms import (
    ConsultationForm,
    FiltreRendezVousForm,
    FiltrePatientForm,
    MajRendezVousForm,
    ReglageTriageForm,
    consultation_pour,
)
from .permissions import administrateur_requis
from .stats import (
    LIBELLES_NIVEAU,
    a_surveiller,
    chiffres_cles,
    chiffres_file,
    nombre_par_patient,
    repartition_par_niveau,
)

PAR_PAGE = 12


def _page(request, queryset):
    return Paginator(queryset, PAR_PAGE).get_page(request.GET.get("page"))


@administrateur_requis
def tableau_de_bord(request):
    lignes = list(Triage.objects.values_list("niveau", "niveau_medecin", "statut"))
    derniers = Triage.objects.select_related("patient__user").order_by("-cree_le")[:8]
    en_attente = suivi.toutes_les_demandes_en_attente()
    suivi.annoter(en_attente)
    return render(request, "backoffice/tableau_de_bord.html", {
        "kpis": chiffres_cles(lignes, Patient.objects.count()),
        "file": chiffres_file([(t.delai.etat, t.protegee) for t in en_attente]),
        "a_surveiller": a_surveiller(en_attente),
        "repartition": repartition_par_niveau(lignes),
        "derniers": derniers,
    })


@administrateur_requis
def rendez_vous(request):
    filtre = FiltreRendezVousForm(request.GET or None)
    demandes = Triage.objects.select_related("patient__user").order_by("-cree_le")
    if filtre.is_valid():
        q = filtre.cleaned_data["q"].strip()
        if q:
            demandes = demandes.filter(
                Q(patient__user__last_name__icontains=q)
                | Q(patient__user__first_name__icontains=q)
                | Q(medecin_nom__icontains=q)
            )
        if filtre.cleaned_data["statut"]:
            demandes = demandes.filter(statut=filtre.cleaned_data["statut"])
        if filtre.cleaned_data["niveau"]:
            demandes = demandes.filter(niveau=int(filtre.cleaned_data["niveau"]))
        if filtre.cleaned_data["medecin"]:
            demandes = demandes.filter(medecin_id=filtre.cleaned_data["medecin"])

    # Les filtres sans le numéro de page, pour les liens de pagination.
    parametres = request.GET.copy()
    parametres.pop("page", None)
    page = _page(request, demandes)
    en_attente = suivi.toutes_les_demandes_en_attente()
    suivi.annoter(en_attente)
    annotees = {t.pk: t for t in en_attente}
    for t in page:
        t.delai = annotees[t.pk].delai if t.pk in annotees else None
    return render(request, "backoffice/rendez_vous.html", {
        "filtre": filtre,
        "page": page,
        "parametres": parametres.urlencode(),
        "filtres_actifs": any(v for v in parametres.values()),
    })


@administrateur_requis
def rendez_vous_detail(request, pk):
    triage = objet_ou_404(Triage.objects.select_related("patient__user"), pk=pk)
    form = MajRendezVousForm(request.POST if request.method == "POST" else None, instance=triage)
    compte_rendu = ConsultationForm(instance=consultation_pour(triage), prefix="cr")
    if request.method == "POST" and form.is_valid():
        termine = form.cleaned_data["statut"] == Triage.Statut.TERMINE
        annule_maintenant = form.cleaned_data["statut"] == Triage.Statut.ANNULE and "statut" in form.changed_data
        if termine:  # un rendez-vous terminé a son compte rendu : c'est lui qui alimente le dossier du patient
            compte_rendu = ConsultationForm(request.POST, instance=compte_rendu.instance, prefix="cr")
        if not termine or compte_rendu.is_valid():
            form.save()
            if annule_maintenant:
                notifications.rendez_vous_annule(triage, request.build_absolute_uri(reverse("patients:medecins")))
            if "statut" in form.changed_data or "niveau_medecin" in form.changed_data:  # l'agenda du médecin a pu bouger
                suivi.prevenir_des_changements(
                    triage.medecin_id, lambda t: request.build_absolute_uri(reverse("patients:resultat", args=[t.pk]))
                )
            if termine:
                compte_rendu.save()
            messages.success(request, "La demande a été mise à jour." + (" Le compte rendu est dans le dossier du patient." if termine else ""))
            return redirect("backoffice:rendez_vous_detail", pk=triage.pk)
    place = None
    if triage.statut == Triage.Statut.EN_ATTENTE:
        du_medecin = list(Triage.objects.filter(medecin_id=triage.medecin_id, statut=Triage.Statut.EN_ATTENTE))
        suivi.annoter(du_medecin)
        triage = next((t for t in du_medecin if t.pk == triage.pk), triage)
        place = triage.place
    return render(request, "backoffice/rendez_vous_detail.html", {
        "triage": triage,
        "form": form,
        "compte_rendu": compte_rendu,
        "place": place,
        "reglage": suivi.reglage_actuel(),
        "allergies_severes": Allergie.objects.filter(
            patient=triage.patient, gravite=Allergie.Gravite.SEVERE, active=True
        ),
    })


def _villes():
    """Les villes des patients, sans doublon (majuscules ignorées), pour le filtre."""
    vues = {}
    for ville in Patient.objects.values_list("ville", flat=True):
        ville = (ville or "").strip()
        if ville:
            vues.setdefault(ville.casefold(), ville)
    return sorted(vues.values(), key=str.casefold)


def _patients_filtres(request):
    """(formulaire de filtre, patients filtrés) : le même filtre sert à la liste et à l'export."""
    filtre = FiltrePatientForm(request.GET or None, villes=_villes())
    liste = Patient.objects.select_related("user").order_by("-cree_le")
    if filtre.is_valid():
        liste = filtre.appliquer(liste)
    return filtre, liste


@administrateur_requis
def patients(request):
    filtre, liste = _patients_filtres(request)
    actifs = filtre.parametres()
    page = _page(request, liste)
    nombres = nombre_par_patient(Triage.objects.values_list("patient", flat=True))
    for p in page:
        p.nb_demandes = nombres.get(str(p.pk), 0)
    return render(request, "backoffice/patients.html", {
        "page": page,
        "filtre": filtre,
        "filtres_actifs": bool(actifs),
        "parametres": urlencode(actifs),
    })


@administrateur_requis
def patients_exporter(request):
    """Télécharge la liste des patients (selon les filtres en cours) au format CSV, lisible dans Excel."""
    _, liste = _patients_filtres(request)
    nombres = nombre_par_patient(Triage.objects.values_list("patient", flat=True))
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = 'attachment; filename="patients-mediconnect.csv"'
    reponse.write("\ufeff")  # signature UTF-8 : Excel affiche bien les accents
    ecrivain = csv.writer(reponse, delimiter=";")
    ecrivain.writerow(["Nom", "Prénom", "E-mail", "Téléphone", "Sexe", "Date de naissance", "Âge", "Ville", "Compte", "Inscrit le", "Demandes"])
    for p in liste:
        ecrivain.writerow([
            proteger_tableur(p.user.last_name), proteger_tableur(p.user.first_name), proteger_tableur(p.user.email),
            proteger_tableur(p.telephone), p.get_sexe_display(), p.date_naissance.strftime("%d/%m/%Y"), p.age,
            proteger_tableur(p.ville), "actif" if p.user.is_active else "désactivé",
            timezone.localtime(p.cree_le).strftime("%d/%m/%Y"), nombres.get(str(p.pk), 0),
        ])
    return reponse


def _compte_modifiable(request, patient):
    """Un compte du personnel ne se désactive pas depuis la liste des patients."""
    if gestion_compte.peut_etre_ferme(patient.user):
        return True
    messages.error(request, "Ce compte appartient au personnel : il ne peut pas être désactivé ici.")
    return False


@administrateur_requis
@require_POST
def patient_desactiver(request, pk):
    patient = objet_ou_404(Patient.objects.select_related("user"), pk=pk)
    if _compte_modifiable(request, patient):
        if not patient.user.is_active:
            messages.info(request, "Ce compte est déjà désactivé.")
        else:
            annulees = gestion_compte.desactiver(patient.user)
            messages.success(
                request,
                f"Le compte de {patient} est désactivé." + (f" {annulees} demande(s) en attente annulée(s)." if annulees else ""),
            )
    return redirect("backoffice:patient_detail", pk=patient.pk)


@administrateur_requis
@require_POST
def patient_reactiver(request, pk):
    patient = objet_ou_404(Patient.objects.select_related("user"), pk=pk)
    if _compte_modifiable(request, patient):
        if patient.user.is_active:
            messages.info(request, "Ce compte est déjà actif.")
        else:
            gestion_compte.reactiver(patient.user)
            messages.success(request, f"Le compte de {patient} est réactivé.")
    return redirect("backoffice:patient_detail", pk=patient.pk)


@administrateur_requis
def patient_detail(request, pk):
    patient = objet_ou_404(Patient.objects.select_related("user"), pk=pk)
    return render(request, "backoffice/patient_detail.html", {
        "patient": patient,
        "dossier": DossierMedical.objects.filter(patient=patient).first(),
        "allergies": Allergie.objects.filter(patient=patient).order_by("-active", "substance"),
        "mesures": sorted(Mesure.objects.filter(patient=patient), key=lambda m: m.mesure_le, reverse=True)[:10],
        "analyse": analyse_service.analyser_patient(patient, ia=analyse_service.CACHE),
        "demandes": Triage.objects.filter(patient=patient).order_by("-cree_le"),
        "consultations": sorted(Consultation.objects.filter(patient=patient), key=lambda c: c.date, reverse=True),
    })


@administrateur_requis
def symptomes(request):
    return render(request, "backoffice/symptomes.html", {
        "symptomes": Symptome.objects.order_by("nom"),
    })


@administrateur_requis
def file_attente(request):
    """Vue d'ensemble de la file : pour chaque médecin, la file (ordre de passage) et les rendez-vous fixés."""
    en_attente = suivi.toutes_les_demandes_en_attente()
    groupes = suivi.annoter(en_attente)
    medecins = list(medecins_test.tous())
    connus = {m["id"] for m in medecins}
    # demandes d'un médecin qui n'est plus dans la liste : on les montre quand même
    for t in en_attente:
        if t.medecin_id not in connus:
            connus.add(t.medecin_id)
            medecins.append({"id": t.medecin_id, "nom": t.medecin_nom, "specialite": t.medecin_specialite})
    sections = []
    for m in medecins:
        g = groupes.get(m["id"], {"file": [], "planning": []})
        toutes = g["file"] + g["planning"]
        sections.append({
            "medecin": m,
            "file": g["file"],
            "planning": g["planning"],
            "en_retard": sum(1 for t in toutes if t.delai.etat == "en_retard"),
            "a_risque": sum(1 for t in toutes if t.delai.etat == "a_risque"),
        })
    reglage = suivi.reglage_actuel()
    return render(request, "backoffice/file_attente.html", {
        "sections": sections,
        "chiffres": chiffres_file([(t.delai.etat, t.protegee) for t in en_attente]),
        "delais": [(n, LIBELLES_NIVEAU[n], reglage.delais[n]) for n in (2, 3, 4, 5)],
        "reglage": reglage,
    })


@administrateur_requis
def parametres(request):
    """Réglages de la file d'attente (délais cibles, plafond de dépassements) et raccourcis d'administration."""
    if request.method == "POST" and "tester_ia" in request.POST:
        resultat = ia_client.tester_connexion()
        if resultat.ok:
            messages.success(request, f"Connexion à l'IA réussie en {resultat.duree_ms} ms.")
        else:
            messages.error(request, f"Connexion à l'IA impossible : {resultat.message}")
        return redirect("backoffice:parametres")
    reglage = ReglageTriage.actuel()
    if request.method == "POST" and "defaut" in request.POST:
        for champ in ReglageTriageForm._meta.model._meta.get_fields():
            if getattr(champ, "name", "") in ReglageTriageForm.base_fields:
                setattr(reglage, champ.name, champ.default)
        reglage.save()
        messages.success(request, "Les valeurs par défaut ont été rétablies.")
        return redirect("backoffice:parametres")
    form = ReglageTriageForm(request.POST if request.method == "POST" else None, instance=reglage)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Les réglages de la file d'attente ont été enregistrés.")
        return redirect("backoffice:parametres")
    return render(request, "backoffice/parametres.html", {"form": form, "ia": ia_client.description()})


@administrateur_requis
def modele_texte(request):
    """Le modèle qui lit le texte libre des patients : ses chiffres d'évaluation, les mots qui pèsent, un essai en direct,
    et le réentraînement."""
    if request.method == "POST" and "reentrainer" in request.POST:
        entraine, evaluation = modele_ia.entrainer()
        modele_ia.sauvegarder(entraine, evaluation)
        modele_ia.installer(entraine)
        messages.success(request, "Le modèle a été réentraîné et enregistré.")
        return redirect("backoffice:modele_texte")
    texte = request.GET.get("texte", "").strip()[:500]
    seuil = ReglageTriage.actuel().seuil_modele
    essai = modele_ia.predire(texte) if texte else None
    evaluation = modele_ia.charger_evaluation()
    return render(request, "backoffice/modele_texte.html", {
        "evaluation": evaluation,
        "jeux": [("Phrases générées (test)", evaluation["test_genere"]), ("Phrases écrites à la main (contrôle)", evaluation["test_a_la_main"])] if evaluation else [],
        "texte": texte,
        "essai": essai,
        "essai_probas": sorted(((int(n), p) for n, p in essai["probas"].items())) if essai else [],
        "essai_final": decision_ia.relever(5, essai, seuil / 100)[0] if essai else None,
        "seuil": seuil,
    })
