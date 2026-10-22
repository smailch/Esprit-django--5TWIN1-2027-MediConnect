from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render

from core.utils import objet_ou_404
from patients import analyse_service, ia_client, medecins_test, suivi
from patients.models import Allergie, DossierMedical, Mesure, Patient, ReglageTriage, Symptome, Triage

from .forms import FiltreRendezVousForm, MajRendezVousForm, ReglageTriageForm
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
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "La demande a été mise à jour.")
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
        "place": place,
        "reglage": suivi.reglage_actuel(),
        "allergies_severes": Allergie.objects.filter(
            patient=triage.patient, gravite=Allergie.Gravite.SEVERE, active=True
        ),
    })


@administrateur_requis
def patients(request):
    q = request.GET.get("q", "").strip()
    liste = Patient.objects.select_related("user").order_by("-cree_le")
    if q:
        liste = liste.filter(
            Q(user__last_name__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__email__icontains=q)
            | Q(telephone__icontains=q)
            | Q(ville__icontains=q)
        )
    page = _page(request, liste)
    nombres = nombre_par_patient(Triage.objects.values_list("patient", flat=True))
    for p in page:
        p.nb_demandes = nombres.get(str(p.pk), 0)
    return render(request, "backoffice/patients.html", {
        "page": page,
        "q": q,
        "parametres": urlencode({"q": q}) if q else "",
    })


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
