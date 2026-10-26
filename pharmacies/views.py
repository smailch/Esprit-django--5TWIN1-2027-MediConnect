from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404
from patients.models import Allergie, Consultation

from . import stats
from .forms import FiltreOrdonnancesForm, FiltrePharmaciesForm, OrdonnanceForm, PharmacieForm, TransmissionForm
from .models import Ordonnance, Pharmacie
from .permissions import ADMIN, PATIENT, PHARMACIE, PRESCRIPTEURS, TOUS, espace_de, espace_requis, patient_de, pharmacie_de

PAR_PAGE = 12


def _page(request, liste):
    return Paginator(liste, PAR_PAGE).get_page(request.GET.get("page"))


# --- Tableau de bord de la pharmacie (page d'arrivée après la connexion) ---------------------------------------

@login_required
def tableau_de_bord(request):
    """Informations générales et statistiques simples de la pharmacie connectée.

    Un compte « pharmacie » pas encore validé (ou sans fiche) arrive aussi ici après la connexion : il voit une page
    qui lui explique pourquoi il doit attendre, plutôt qu'une erreur 403."""
    request.espace = espace_de(request.user)
    if request.espace != PHARMACIE:
        if getattr(request.user, "role", None) != PHARMACIE:
            raise PermissionDenied("Cette page ne fait pas partie de votre espace.")
        return render(request, "pharmacies/en_attente.html", {
            "sans_fiche": request.user.est_valide and pharmacie_de(request.user) is None,
        })
    pharmacie = pharmacie_de(request.user)
    ordonnances = list(Ordonnance.objects.filter(pharmacie=pharmacie).select_related("patient__user"))
    return render(request, "pharmacies/tableau_de_bord.html", {
        "pharmacie": pharmacie,
        "kpis": stats.chiffres_cles(ordonnances),
        "a_traiter": stats.a_traiter(ordonnances),
        "a_relancer": stats.a_relancer(ordonnances),
        "repartition": stats.repartition_par_statut(ordonnances),
        "semaine": stats.delivrees_par_jour(ordonnances),
        "frequents": stats.medicaments_frequents(ordonnances),
        "jours_relance": stats.JOURS_AVANT_RELANCE,
    })


# --- Annuaire des pharmacies : liste, fiche, ajout, modification, suppression -------------------------

@espace_requis(*TOUS)
def pharmacies(request):
    filtre = FiltrePharmaciesForm(request.GET or None)
    liste = Pharmacie.objects.filter(user__is_active=True)
    if filtre.is_valid():
        q = filtre.cleaned_data["q"].strip()
        if q:
            liste = liste.filter(Q(nom__icontains=q) | Q(ville__icontains=q))
        if filtre.cleaned_data["de_garde"]:
            liste = liste.filter(de_garde=True)
    parametres = request.GET.copy()
    parametres.pop("page", None)
    return render(request, "pharmacies/pharmacies.html", {
        "page": _page(request, liste),
        "filtre": filtre,
        "parametres": parametres.urlencode(),
        "filtres_actifs": any(v for v in parametres.values()),
    })


def _fiche(request, pharmacie):
    """Fiche d'une pharmacie ; l'administrateur et la pharmacie elle-même y voient aussi son activité."""
    proprietaire = request.espace == ADMIN or pharmacie_de(request.user) == pharmacie
    en_cours = []
    if proprietaire:
        actifs = [Ordonnance.Statut.TRANSMISE, Ordonnance.Statut.EN_PREPARATION, Ordonnance.Statut.PRETE]
        en_cours = Ordonnance.objects.filter(pharmacie=pharmacie, statut__in=actifs).select_related("patient__user")
    return render(request, "pharmacies/pharmacie_detail.html", {
        "pharmacie": pharmacie, "proprietaire": proprietaire, "en_cours": en_cours,
    })


@espace_requis(*TOUS)
def pharmacie_detail(request, pk):
    return _fiche(request, objet_ou_404(Pharmacie, pk=pk))


@espace_requis(PHARMACIE)
def ma_pharmacie(request):
    return _fiche(request, pharmacie_de(request.user))


@espace_requis(ADMIN)
def pharmacie_creer(request):
    form = PharmacieForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        pharmacie = form.save()
        messages.success(request, f"La pharmacie « {pharmacie.nom} » a été ajoutée.")
        return redirect("pharmacies:pharmacie_detail", pk=pharmacie.pk)
    return render(request, "pharmacies/pharmacie_form.html", {"form": form, "pharmacie": None})


@espace_requis(ADMIN, PHARMACIE)
def pharmacie_modifier(request, pk):
    pharmacie = objet_ou_404(Pharmacie, pk=pk)
    if request.espace == PHARMACIE and pharmacie_de(request.user) != pharmacie:
        raise PermissionDenied("Vous ne pouvez modifier que votre propre pharmacie.")
    form = PharmacieForm(
        request.POST if request.method == "POST" else None, instance=pharmacie, avec_compte=request.espace == ADMIN
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "La fiche de la pharmacie a été mise à jour.")
        return redirect("pharmacies:pharmacie_detail", pk=pharmacie.pk)
    return render(request, "pharmacies/pharmacie_form.html", {"form": form, "pharmacie": pharmacie})


@espace_requis(ADMIN)
def pharmacie_supprimer(request, pk):
    """GET : demande de confirmation ; POST : suppression, refusée s'il reste des ordonnances en cours."""
    pharmacie = objet_ou_404(Pharmacie, pk=pk)
    actifs = [Ordonnance.Statut.TRANSMISE, Ordonnance.Statut.EN_PREPARATION, Ordonnance.Statut.PRETE]
    en_cours = Ordonnance.objects.filter(pharmacie=pharmacie, statut__in=actifs).count()
    if request.method == "POST":
        if en_cours:
            messages.error(request, f"Impossible : {en_cours} ordonnance(s) sont encore en cours dans cette pharmacie.")
            return redirect("pharmacies:pharmacie_detail", pk=pharmacie.pk)
        nom = pharmacie.nom
        pharmacie.delete()
        messages.success(request, f"La pharmacie « {nom} » a été supprimée.")
        return redirect("pharmacies:pharmacies")
    return render(request, "pharmacies/pharmacie_supprimer.html", {"pharmacie": pharmacie, "en_cours": en_cours})


# --- Ordonnances ------------------------------------------------------------------------------------------

def ordonnances_visibles(request):
    """Les ordonnances que le compte connecté a le droit de voir. Toute recherche par identifiant part de là :
    l'ordonnance d'un autre patient (ou d'une autre pharmacie) répond « introuvable » (404), sans révéler qu'elle existe."""
    toutes = Ordonnance.objects.select_related("patient__user", "pharmacie")
    if request.espace in PRESCRIPTEURS:
        return toutes
    if request.espace == PHARMACIE:
        return toutes.filter(pharmacie=pharmacie_de(request.user))
    if request.espace == PATIENT:
        return toutes.filter(patient=patient_de(request.user))
    raise PermissionDenied


def _consultations_sans_ordonnance(limite=8):
    """Les consultations récentes qui n'ont pas encore d'ordonnance : le point de départ du prescripteur."""
    deja = set(Ordonnance.objects.exclude(consultation=None).values_list("consultation", flat=True))
    recentes = Consultation.objects.select_related("patient__user").order_by("-date")[:50]
    return [c for c in recentes if c.pk not in deja][:limite]


@espace_requis(*TOUS)
def ordonnances(request):
    filtre = FiltreOrdonnancesForm(request.GET or None)
    liste = ordonnances_visibles(request)
    if filtre.is_valid() and filtre.cleaned_data["statut"]:
        liste = liste.filter(statut=filtre.cleaned_data["statut"])
    parametres = request.GET.copy()
    parametres.pop("page", None)
    return render(request, "pharmacies/ordonnances.html", {
        "page": _page(request, liste),
        "filtre": filtre,
        "parametres": parametres.urlencode(),
        "filtres_actifs": any(v for v in parametres.values()),
        "a_rediger": _consultations_sans_ordonnance() if request.espace in PRESCRIPTEURS else [],
    })


@espace_requis(*TOUS)
def ordonnance_detail(request, pk):
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    # Le pharmacien et le prescripteur voient les allergies actives : c'est le dernier contrôle avant la remise.
    allergies = []
    if request.espace != PATIENT:
        allergies = Allergie.objects.filter(patient=ordonnance.patient, active=True).order_by("substance")
    return render(request, "pharmacies/ordonnance_detail.html", {
        "ordonnance": ordonnance,
        "allergies": allergies,
        "etapes": [(s, Ordonnance.Statut(s).label) for s in Ordonnance.PARCOURS],
    })


@espace_requis(*PRESCRIPTEURS)
def ordonnance_creer(request, consultation_pk):
    consultation = objet_ou_404(Consultation.objects.select_related("patient__user"), pk=consultation_pk)
    ordonnance = Ordonnance(patient=consultation.patient, consultation=consultation, prescripteur_nom=consultation.medecin_nom)
    if request.method == "POST":
        form = OrdonnanceForm(request.POST, instance=ordonnance)
        if form.is_valid():
            ordonnance = form.save()
            messages.success(request, f"L'ordonnance {ordonnance.reference} a été créée. Le patient peut la transmettre à sa pharmacie.")
            return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
    else:
        form = OrdonnanceForm(instance=ordonnance, initial={"medicaments": consultation.prescription})  # prérempli
    return render(request, "pharmacies/ordonnance_form.html", {"form": form, "ordonnance": None, "consultation": consultation})


@espace_requis(*PRESCRIPTEURS)
def ordonnance_modifier(request, pk):
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_modifiable:
        messages.error(request, "La pharmacie a commencé la préparation : l'ordonnance ne peut plus être modifiée.")
        return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
    form = OrdonnanceForm(request.POST if request.method == "POST" else None, instance=ordonnance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "L'ordonnance a été mise à jour.")
        return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
    return render(request, "pharmacies/ordonnance_form.html", {
        "form": form, "ordonnance": ordonnance, "consultation": ordonnance.consultation,
    })


@espace_requis(*PRESCRIPTEURS)
def ordonnance_supprimer(request, pk):
    """GET : demande de confirmation ; POST : suppression (seulement avant la préparation, ou si elle est annulée)."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_supprimable:
        messages.error(request, "Une ordonnance préparée ou délivrée est conservée : annulez-la plutôt.")
        return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
    if request.method == "POST":
        reference = ordonnance.reference
        ordonnance.delete()
        messages.success(request, f"L'ordonnance {reference} a été supprimée.")
        return redirect("pharmacies:ordonnances")
    return render(request, "pharmacies/ordonnance_supprimer.html", {"ordonnance": ordonnance})


@espace_requis(*PRESCRIPTEURS)
@require_POST
def ordonnance_annuler(request, pk):
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if ordonnance.est_annulable:
        ordonnance.statut = Ordonnance.Statut.ANNULEE
        ordonnance.save(update_fields=["statut", "modifie_le"])
        messages.success(request, "L'ordonnance est annulée : la pharmacie ne la délivrera pas.")
    return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)


@espace_requis(PATIENT)
def ordonnance_transmettre(request, pk):
    """Le patient choisit (ou change) la pharmacie qui préparera son ordonnance."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_transmissible:
        messages.error(request, "Cette ordonnance ne peut plus être envoyée à une pharmacie.")
        return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
    form = TransmissionForm(
        request.POST if request.method == "POST" else None,
        initial={"pharmacie": ordonnance.pharmacie_id},
    )
    if request.method == "POST" and form.is_valid():
        ordonnance.pharmacie = form.cleaned_data["pharmacie"]
        ordonnance.statut = Ordonnance.Statut.TRANSMISE
        ordonnance.save(update_fields=["pharmacie", "statut", "modifie_le"])
        messages.success(request, f"Votre ordonnance a été envoyée à {ordonnance.pharmacie.nom}.")
        return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
    return render(request, "pharmacies/ordonnance_transmettre.html", {"form": form, "ordonnance": ordonnance})


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_avancer(request, pk):
    """La pharmacie passe l'ordonnance à l'étape suivante : en préparation, prête, délivrée."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    try:
        nouveau = ordonnance.avancer()
    except ValueError as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, f"Ordonnance {ordonnance.reference} : {Ordonnance.Statut(nouveau).label.lower()}.")
    return redirect("pharmacies:ordonnance_detail", pk=ordonnance.pk)
