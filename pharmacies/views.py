from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404
from patients import ia_client
from patients.models import Allergie, Consultation

from . import ia_substitution, stats
from .forms import FiltreOrdonnancesForm, FiltrePharmaciesForm, OrdonnanceForm, PharmacieForm, RuptureForm, TransmissionForm
from .models import Ordonnance, Pharmacie
from .permissions import ADMIN, PATIENT, PHARMACIE, PRESCRIPTEURS, TOUS, espace_de, espace_requis, patient_de, pharmacie_de

PAR_PAGE = 12


def _page(request, liste):
    return Paginator(liste, PAR_PAGE).get_page(request.GET.get("page"))


def _redirection(request, nom, *args):
    """Redirige en restant dans la même entrée du module : /pharmacies/ ou /backoffice/pharmacies/ (administrateur)."""
    entree = getattr(getattr(request, "resolver_match", None), "namespace", None)
    return redirect(reverse(f"pharmacies:{nom}", args=args, current_app=entree))


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
        return _redirection(request, "pharmacie_detail", pharmacie.pk)
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
        return _redirection(request, "pharmacie_detail", pharmacie.pk)
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
            return _redirection(request, "pharmacie_detail", pharmacie.pk)
        nom = pharmacie.nom
        pharmacie.delete()
        messages.success(request, f"La pharmacie « {nom} » a été supprimée.")
        return _redirection(request, "pharmacies")
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
    rupture = None
    if request.espace == PHARMACIE and ordonnance.est_en_traitement:
        rupture = RuptureForm(lignes=ordonnance.lignes)
    return render(request, "pharmacies/ordonnance_detail.html", {
        "ordonnance": ordonnance,
        "allergies": allergies,
        "etapes": [(s, Ordonnance.Statut(s).label) for s in Ordonnance.PARCOURS],
        "rupture": rupture,
    })


# --- Rupture de stock : signalement et suggestion de remplaçants par l'IA ---------------------------------------

MESSAGES_SOURCE = {
    ia_substitution.IA: "Proposé par l'IA, à vérifier : même principe actif, dosage et forme à contrôler.",
    ia_substitution.LOCAL: "IA indisponible : suggestions tirées de la table locale des génériques.",
    ia_substitution.AUCUNE: "Aucun équivalent connu pour ce médicament. Vérifiez auprès de votre grossiste ou du prescripteur.",
}


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_substitution(request, pk):
    """Suggestions de remplaçants pour un médicament de l'ordonnance (appel asynchrone, réponse JSON).

    Seul le nom du médicament part vers l'IA ; les allergies du patient sont confrontées aux suggestions ici, en local.
    Le médicament doit être une ligne de cette ordonnance : la page n'est pas un accès libre à l'IA."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_en_traitement:
        return JsonResponse({"ok": False, "erreur": "Les remplaçants se cherchent pendant la préparation de l'ordonnance."}, status=400)
    ligne = request.POST.get("medicament", "")
    if ligne not in ordonnance.lignes or not ia_substitution.nettoyer(ligne):
        return JsonResponse({"ok": False, "erreur": "Choisissez d'abord le médicament en rupture."}, status=400)
    resultat = ia_substitution.suggerer(ligne, identifiant=f"pharmacie:{ordonnance.pharmacie_id}")
    substances = list(Allergie.objects.filter(patient=ordonnance.patient, active=True).values_list("substance", flat=True))
    suggestions = ia_substitution.signaler_allergies(resultat.suggestions, resultat.principe_actif, substances)
    message = MESSAGES_SOURCE[resultat.source]
    if resultat.source != ia_substitution.IA and resultat.statut in ia_client.MESSAGES:
        message += f" ({ia_client.MESSAGES[resultat.statut]})"
    return JsonResponse({
        "ok": True,
        "medicament": ia_substitution.nettoyer(ligne),
        "source": resultat.source,
        "statut": resultat.statut,
        "message": message,
        "principe_actif": resultat.principe_actif,
        "suggestions": suggestions,
        "duree_ms": resultat.duree_ms,
        "en_cache": resultat.en_cache,
    })


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_rupture(request, pk):
    """Enregistre la rupture (et le remplaçant choisi par le pharmacien) dans la note visible du patient et du prescripteur."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_en_traitement:
        messages.error(request, "La rupture se signale pendant la préparation de l'ordonnance.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    form = RuptureForm(request.POST, lignes=ordonnance.lignes)
    if form.is_valid():
        note = f"Rupture de stock : {ia_substitution.nettoyer(form.cleaned_data['medicament'])}."
        if form.cleaned_data["remplacant"].strip():
            note += f" Remplaçant proposé par la pharmacie : {form.cleaned_data['remplacant'].strip()} (à confirmer avec le patient)."
        ordonnance.note_pharmacien = note[:300]
        ordonnance.save(update_fields=["note_pharmacien", "modifie_le"])
        messages.success(request, "La rupture est signalée : le patient et le prescripteur la voient sur l'ordonnance.")
    else:
        messages.error(request, "Choisissez le médicament en rupture.")
    return _redirection(request, "ordonnance_detail", ordonnance.pk)


@espace_requis(*PRESCRIPTEURS)
def ordonnance_creer(request, consultation_pk):
    consultation = objet_ou_404(Consultation.objects.select_related("patient__user"), pk=consultation_pk)
    ordonnance = Ordonnance(patient=consultation.patient, consultation=consultation, prescripteur_nom=consultation.medecin_nom)
    if request.method == "POST":
        form = OrdonnanceForm(request.POST, instance=ordonnance)
        if form.is_valid():
            ordonnance = form.save()
            messages.success(request, f"L'ordonnance {ordonnance.reference} a été créée. Le patient peut la transmettre à sa pharmacie.")
            return _redirection(request, "ordonnance_detail", ordonnance.pk)
    else:
        form = OrdonnanceForm(instance=ordonnance, initial={"medicaments": consultation.prescription})  # prérempli
    return render(request, "pharmacies/ordonnance_form.html", {"form": form, "ordonnance": None, "consultation": consultation})


@espace_requis(*PRESCRIPTEURS)
def ordonnance_modifier(request, pk):
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_modifiable:
        messages.error(request, "La pharmacie a commencé la préparation : l'ordonnance ne peut plus être modifiée.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    form = OrdonnanceForm(request.POST if request.method == "POST" else None, instance=ordonnance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "L'ordonnance a été mise à jour.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    return render(request, "pharmacies/ordonnance_form.html", {
        "form": form, "ordonnance": ordonnance, "consultation": ordonnance.consultation,
    })


@espace_requis(*PRESCRIPTEURS)
def ordonnance_supprimer(request, pk):
    """GET : demande de confirmation ; POST : suppression (seulement avant la préparation, ou si elle est annulée)."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_supprimable:
        messages.error(request, "Une ordonnance préparée ou délivrée est conservée : annulez-la plutôt.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    if request.method == "POST":
        reference = ordonnance.reference
        ordonnance.delete()
        messages.success(request, f"L'ordonnance {reference} a été supprimée.")
        return _redirection(request, "ordonnances")
    return render(request, "pharmacies/ordonnance_supprimer.html", {"ordonnance": ordonnance})


@espace_requis(*PRESCRIPTEURS)
@require_POST
def ordonnance_annuler(request, pk):
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if ordonnance.est_annulable:
        ordonnance.statut = Ordonnance.Statut.ANNULEE
        ordonnance.save(update_fields=["statut", "modifie_le"])
        messages.success(request, "L'ordonnance est annulée : la pharmacie ne la délivrera pas.")
    return _redirection(request, "ordonnance_detail", ordonnance.pk)


@espace_requis(PATIENT)
def ordonnance_transmettre(request, pk):
    """Le patient choisit (ou change) la pharmacie qui préparera son ordonnance."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_transmissible:
        messages.error(request, "Cette ordonnance ne peut plus être envoyée à une pharmacie.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    form = TransmissionForm(
        request.POST if request.method == "POST" else None,
        initial={"pharmacie": ordonnance.pharmacie_id},
    )
    if request.method == "POST" and form.is_valid():
        ordonnance.pharmacie = form.cleaned_data["pharmacie"]
        ordonnance.statut = Ordonnance.Statut.TRANSMISE
        ordonnance.save(update_fields=["pharmacie", "statut", "modifie_le"])
        messages.success(request, f"Votre ordonnance a été envoyée à {ordonnance.pharmacie.nom}.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
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
    return _redirection(request, "ordonnance_detail", ordonnance.pk)
