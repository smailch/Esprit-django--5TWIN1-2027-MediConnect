from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render

from core.utils import objet_ou_404
from patients.models import Allergie, DossierMedical, Mesure, Patient, Symptome, Triage

from .forms import FiltreRendezVousForm, MajRendezVousForm
from .permissions import administrateur_requis
from .stats import chiffres_cles, nombre_par_patient, repartition_par_niveau

PAR_PAGE = 12


def _page(request, queryset):
    return Paginator(queryset, PAR_PAGE).get_page(request.GET.get("page"))


@administrateur_requis
def tableau_de_bord(request):
    lignes = list(Triage.objects.values_list("niveau", "niveau_medecin", "statut"))
    derniers = Triage.objects.select_related("patient__user").order_by("-cree_le")[:8]
    return render(request, "backoffice/tableau_de_bord.html", {
        "kpis": chiffres_cles(lignes, Patient.objects.count()),
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
    return render(request, "backoffice/rendez_vous.html", {
        "filtre": filtre,
        "page": _page(request, demandes),
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
    return render(request, "backoffice/rendez_vous_detail.html", {
        "triage": triage,
        "form": form,
        "place": triage.place_dans_la_file(),
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
        "demandes": Triage.objects.filter(patient=patient).order_by("-cree_le"),
    })


@administrateur_requis
def symptomes(request):
    return render(request, "backoffice/symptomes.html", {
        "symptomes": Symptome.objects.order_by("nom"),
    })
