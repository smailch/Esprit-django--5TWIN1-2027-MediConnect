from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404
from patients import ia_client
from patients.models import Allergie, Consultation

from . import delivrance, ia_substitution, remplacements, stats, stock
from .forms import (
    FiltreOrdonnancesForm,
    FiltrePharmaciesForm,
    FiltreStockForm,
    MedicamentForm,
    OrdonnanceForm,
    PharmacieForm,
    RuptureForm,
    TransmissionForm,
)
from .models import Medicament, Ordonnance, Pharmacie, Remplacement
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
        "stock": stats.chiffres_stock(list(Medicament.objects.filter(pharmacie=pharmacie))),
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
    page = _page(request, liste)
    # Ordonnances de la page avec un remplaçant en attente de réponse (une seule requête pour toute la page).
    propositions = set(Remplacement.objects.filter(
        ordonnance_id__in=[o.pk for o in page], statut=Remplacement.Statut.PROPOSE
    ).values_list("ordonnance_id", flat=True)) if len(page) else set()
    for o in page:
        o.remplacement_en_attente = o.pk in propositions
    return render(request, "pharmacies/ordonnances.html", {
        "page": page,
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
    rupture, etats, manquants, disponibles, decision = None, [], [], [], None
    accord = Ordonnance.Accord
    if request.espace == PHARMACIE:
        # Chaque ligne confrontée au stock réel de la pharmacie : la rupture se constate, elle ne se déclare pas.
        etats = stock.etat_des_lignes(ordonnance.lignes, list(Medicament.objects.filter(pharmacie=ordonnance.pharmacie)))
        manquants = stock.lignes_en_rupture(etats)
        if ordonnance.est_en_traitement:
            rupture = RuptureForm(lignes=ordonnance.lignes, initial={"medicament": manquants[0] if manquants else ""})
    elif request.espace == PATIENT and ordonnance.accord_partiel == accord.EN_ATTENTE:
        decision = _choix_du_patient(ordonnance)
    elif request.espace == PATIENT and ordonnance.est_transmissible:
        # Le patient voit où ses médicaments sont réellement en stock (utile surtout pour le reste d'une délivrance partielle).
        disponibles = delivrance.pharmacies_disponibles(ordonnance.lignes, exclure=ordonnance.pharmacie, ville=ordonnance.patient.ville)
    servies = len(etats) - len(manquants)
    return render(request, "pharmacies/ordonnance_detail.html", {
        "ordonnance": ordonnance,
        "allergies": allergies,
        "etapes": [(s, Ordonnance.Statut(s).label) for s in Ordonnance.PARCOURS],
        "rupture": rupture,
        "etats": etats,
        "manquants": manquants,
        "servies": servies,
        # Délivrer : au moins un médicament en stock et, s'il en manque, l'accord du patient pour une délivrance partielle.
        "peut_avancer": bool(ordonnance.statut_suivant) and (
            ordonnance.statut_suivant != Ordonnance.Statut.DELIVREE or (servies > 0 and (not manquants or ordonnance.accord_partiel == accord.ACCEPTE))
        ),
        "accord_demandable": request.espace == PHARMACIE and delivrance.accord_demandable(ordonnance, etats),
        "decision": decision,
        "remplacements": list(ordonnance.remplacements.all()),
        "disponibles": disponibles,
        "reliquats": list(ordonnance.reliquats.all()) if ordonnance.statut == Ordonnance.Statut.DELIVREE else [],
    })


def _choix_du_patient(ordonnance):
    """Ce dont le patient a besoin pour répondre à une demande de délivrance partielle : ce que sa pharmacie a, ce qui
    manque, où trouver le reste (s'il accepte) et où tout trouver (s'il refuse). D'après les stocks réels."""
    etats = stock.etat_des_lignes(ordonnance.lignes, list(Medicament.objects.filter(pharmacie=ordonnance.pharmacie)))
    manquants = stock.lignes_en_rupture(etats)
    ville = ordonnance.patient.ville
    return {
        "servies": delivrance.lignes_servies(etats),
        "manquants": manquants,
        "pour_le_reste": delivrance.pharmacies_disponibles(manquants, exclure=ordonnance.pharmacie, ville=ville),
        "pour_tout": [d for d in delivrance.pharmacies_disponibles(ordonnance.lignes, exclure=ordonnance.pharmacie, ville=ville) if d["complete"]],
    }


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_demander_accord(request, pk):
    """Il manque des médicaments : la pharmacie demande au patient s'il accepte une délivrance partielle."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    etats = stock.etat_des_lignes(ordonnance.lignes, list(Medicament.objects.filter(pharmacie=ordonnance.pharmacie)))
    if not delivrance.accord_demandable(ordonnance, etats):
        messages.error(request, "Une délivrance partielle ne peut pas être proposée pour cette ordonnance.")
    else:
        ordonnance.accord_partiel = Ordonnance.Accord.EN_ATTENTE
        ordonnance.save(update_fields=["accord_partiel", "modifie_le"])
        messages.success(request, "Le patient a été sollicité : il choisira entre une délivrance partielle ici ou une autre pharmacie.")
    return _redirection(request, "ordonnance_detail", ordonnance.pk)


@espace_requis(PATIENT)
@require_POST
def ordonnance_decision(request, pk):
    """Réponse du patient à une demande de délivrance partielle.

    accepter : il retire ici ce qui est en stock ; le reste partira (éventuellement vers la pharmacie qu'il choisit).
    refuser  : toute l'ordonnance est transférée à une autre pharmacie, qui reprend la préparation depuis le début."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if ordonnance.accord_partiel != Ordonnance.Accord.EN_ATTENTE or ordonnance.statut == Ordonnance.Statut.DELIVREE:
        messages.error(request, "Aucune réponse n'est attendue pour cette ordonnance.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    action = request.POST.get("action")
    choisie = None
    if request.POST.get("pharmacie"):
        form = TransmissionForm(request.POST)
        if not form.is_valid() or form.cleaned_data["pharmacie"] == ordonnance.pharmacie:
            messages.error(request, "Choisissez une autre pharmacie de la liste.")
            return _redirection(request, "ordonnance_detail", ordonnance.pk)
        choisie = form.cleaned_data["pharmacie"]
    if action == "accepter":
        ordonnance.accord_partiel, ordonnance.pharmacie_reste = Ordonnance.Accord.ACCEPTE, choisie
        ordonnance.save(update_fields=["accord_partiel", "pharmacie_reste", "modifie_le"])
        messages.success(request, f"C'est noté : retirez chez {ordonnance.pharmacie.nom} les médicaments disponibles. " + (
            f"Le reste sera envoyé à {choisie.nom}." if choisie else "Vous enverrez le reste à la pharmacie de votre choix."
        ))
    elif action == "refuser" and choisie is not None:
        ancienne = ordonnance.pharmacie.nom
        ordonnance.pharmacie, ordonnance.statut = choisie, Ordonnance.Statut.TRANSMISE
        ordonnance.accord_partiel, ordonnance.pharmacie_reste = Ordonnance.Accord.NON_DEMANDE, None
        ordonnance.note_pharmacien = f"Transférée par le patient : {ancienne} n'avait pas tous les médicaments."[:300]
        ordonnance.save(update_fields=["pharmacie", "statut", "accord_partiel", "pharmacie_reste", "note_pharmacien", "modifie_le"])
        messages.success(request, f"Votre ordonnance complète a été envoyée à {choisie.nom}.")
    else:
        messages.error(request, "Choisissez la pharmacie qui préparera toute votre ordonnance.")
    return _redirection(request, "ordonnance_detail", ordonnance.pk)


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
    medicaments = list(Medicament.objects.filter(pharmacie=ordonnance.pharmacie))
    # Le principe actif connu par le stock est donné à l'IA, qui ne peut alors pas se tromper de molécule.
    resultat = ia_substitution.suggerer(
        ligne, identifiant=f"pharmacie:{ordonnance.pharmacie_id}", principe=stock.principe_de(ligne, medicaments)
    )
    substances = list(Allergie.objects.filter(patient=ordonnance.patient, active=True).values_list("substance", flat=True))
    principe = stock.principe_de(ligne, medicaments) or resultat.principe_actif
    # D'abord ce que la pharmacie a réellement en rayon (même principe actif), calculé en local…
    en_stock = [
        {"nom": str(m), "type": "en_stock", "type_libelle": "Dans votre stock", "raison": f"Même principe actif : {m.principe_actif}.",
         "stock": m.quantite, "source": Remplacement.Source.STOCK}
        for m in stock.equivalents_en_stock(principe, medicaments, exclure=stock.trouver(ligne, medicaments))
    ][:ia_substitution.MAX_SUGGESTIONS]
    ia_substitution.signaler_allergies(en_stock, principe, substances)
    # … puis les suggestions de l'IA (ou de la table locale), avec la quantité disponible ici.
    suggestions = stock.annoter_stock(ia_substitution.signaler_allergies(resultat.suggestions, principe, substances), medicaments)
    for s in suggestions:
        s["source"] = resultat.source  # « ia » ou « local » : gardé dans la trace si le pharmacien la propose
    message = MESSAGES_SOURCE[resultat.source]
    if resultat.source != ia_substitution.IA and resultat.statut in ia_client.MESSAGES:
        message += f" ({ia_client.MESSAGES[resultat.statut]})"
    return JsonResponse({
        "ok": True,
        "medicament": ia_substitution.nettoyer(ligne),
        "source": resultat.source,
        "statut": resultat.statut,
        "message": message,
        "principe_actif": principe,
        "en_stock": en_stock,
        "suggestions": suggestions,
        "duree_ms": resultat.duree_ms,
        "en_cache": resultat.en_cache,
    })


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_rupture(request, pk):
    """Médicament en rupture : la pharmacie propose un remplaçant au patient (action « proposer »), ou signale
    simplement la rupture dans la note visible du patient et du prescripteur (action « signaler »)."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if not ordonnance.est_en_traitement:
        messages.error(request, "La rupture se signale pendant la préparation de l'ordonnance.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    form = RuptureForm(request.POST, lignes=ordonnance.lignes)
    if not form.is_valid():
        messages.error(request, "Choisissez le médicament en rupture.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    ligne, remplacant = form.cleaned_data["medicament"], form.cleaned_data["remplacant"]
    if request.POST.get("action") == "signaler":
        ordonnance.note_pharmacien = f"Rupture de stock : {ia_substitution.nettoyer(ligne)}."[:300]
        ordonnance.save(update_fields=["note_pharmacien", "modifie_le"])
        messages.success(request, "La rupture est signalée : le patient et le prescripteur la voient sur l'ordonnance.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    medicaments = list(Medicament.objects.filter(pharmacie=ordonnance.pharmacie))
    substances = list(Allergie.objects.filter(patient=ordonnance.patient, active=True).values_list("substance", flat=True))
    try:
        proposition = remplacements.proposer(ordonnance, ligne, remplacant, form.cleaned_data["source"], medicaments, substances)
    except ValueError as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, f"« {proposition.remplacant} » a été proposé au patient à la place de « {ia_substitution.nettoyer(ligne)} ».")
    return _redirection(request, "ordonnance_detail", ordonnance.pk)


@espace_requis(PATIENT)
@require_POST
def remplacement_decision(request, pk, remplacement_pk):
    """Le patient accepte (l'ordonnance est modifiée) ou refuse le remplaçant proposé par sa pharmacie."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    proposition = objet_ou_404(Remplacement, pk=remplacement_pk, ordonnance=ordonnance)  # uniquement sur SON ordonnance
    proposition.ordonnance = ordonnance
    try:
        if request.POST.get("action") == "accepter":
            remplacements.accepter(proposition)
            messages.success(request, f"C'est noté : votre ordonnance contient maintenant {proposition.remplacant}.")
        else:
            remplacements.refuser(proposition)
            messages.success(request, "Proposition refusée : votre ordonnance ne change pas.")
    except ValueError as erreur:
        messages.error(request, str(erreur))
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
    disponibles = delivrance.pharmacies_disponibles(ordonnance.lignes, ville=ordonnance.patient.ville)
    # Par défaut : la pharmacie actuelle, sinon celle qui a le plus de médicaments en stock.
    proposee = ordonnance.pharmacie_id or (disponibles[0]["pharmacie"].pk if disponibles else None)
    form = TransmissionForm(request.POST if request.method == "POST" else None, initial={"pharmacie": proposee})
    if request.method == "POST" and form.is_valid():
        ordonnance.pharmacie = form.cleaned_data["pharmacie"]
        ordonnance.statut = Ordonnance.Statut.TRANSMISE
        ordonnance.save(update_fields=["pharmacie", "statut", "modifie_le"])
        messages.success(request, f"Votre ordonnance a été envoyée à {ordonnance.pharmacie.nom}.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    return render(request, "pharmacies/ordonnance_transmettre.html", {
        "form": form, "ordonnance": ordonnance, "disponibles": disponibles,
    })


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_avancer(request, pk):
    """La pharmacie passe l'ordonnance à l'étape suivante : en préparation, prête, délivrée."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    try:
        if ordonnance.statut_suivant == Ordonnance.Statut.DELIVREE:
            # Seul ce qui est en stock est remis ; le reste part sur une nouvelle ordonnance rendue au patient.
            etats = stock.etat_des_lignes(ordonnance.lignes, list(Medicament.objects.filter(pharmacie=ordonnance.pharmacie)))
            retirees, reste = delivrance.delivrer(ordonnance, etats)
            message = f"Ordonnance {ordonnance.reference} délivrée. {retirees} boîte(s) retirée(s) du stock."
            if reste is not None:
                message += (f" {len(reste.lignes)} médicament(s) non disponible(s) : reportés sur l'ordonnance {reste.reference}, "
                            "le patient voit les pharmacies qui les ont en stock.")
        else:
            nouveau = ordonnance.avancer()
            message = f"Ordonnance {ordonnance.reference} : {Ordonnance.Statut(nouveau).label.lower()}."
    except ValueError as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, message)
    return _redirection(request, "ordonnance_detail", ordonnance.pk)


@espace_requis(PHARMACIE)
@require_POST
def ordonnance_renvoyer(request, pk):
    """La pharmacie ne peut pas servir l'ordonnance : elle la rend au patient, qui l'enverra ailleurs."""
    ordonnance = objet_ou_404(ordonnances_visibles(request), pk=pk)
    if ordonnance.statut not in (Ordonnance.Statut.TRANSMISE, Ordonnance.Statut.EN_PREPARATION, Ordonnance.Statut.PRETE):
        messages.error(request, "Cette ordonnance ne peut plus être renvoyée.")
        return _redirection(request, "ordonnance_detail", ordonnance.pk)
    nom = ordonnance.pharmacie.nom
    ordonnance.statut, ordonnance.pharmacie = Ordonnance.Statut.EMISE, None
    ordonnance.accord_partiel, ordonnance.pharmacie_reste = Ordonnance.Accord.NON_DEMANDE, None
    ordonnance.note_pharmacien = f"Renvoyée par {nom} le {timezone.localdate():%d/%m/%Y} : médicaments non disponibles."[:300]
    ordonnance.save(update_fields=["statut", "pharmacie", "accord_partiel", "pharmacie_reste", "note_pharmacien", "modifie_le"])
    messages.success(request, f"L'ordonnance {ordonnance.reference} a été rendue au patient.")
    return _redirection(request, "ordonnances")


# --- Stock de la pharmacie : liste, ajout, modification, suppression ---------------------------------------------

def _mon_medicament(request, pk):
    """Un médicament du stock de la pharmacie connectée ; celui d'une autre pharmacie répond 404."""
    return objet_ou_404(Medicament, pk=pk, pharmacie=pharmacie_de(request.user))


@espace_requis(PHARMACIE)
def stock_liste(request):
    medicaments = list(Medicament.objects.filter(pharmacie=pharmacie_de(request.user)))
    chiffres = stats.chiffres_stock(medicaments)  # sur tout le stock, avant les filtres
    filtre = FiltreStockForm(request.GET or None)
    if filtre.is_valid():
        q = stock.normaliser(filtre.cleaned_data["q"])
        if q:
            medicaments = [m for m in medicaments if q in stock.normaliser(f"{m.nom} {m.principe_actif}")]
        if filtre.cleaned_data["etat"]:
            medicaments = [m for m in medicaments if m.etat == filtre.cleaned_data["etat"]]
    parametres = request.GET.copy()
    parametres.pop("page", None)
    return render(request, "pharmacies/stock.html", {
        "page": _page(request, medicaments),
        "filtre": filtre,
        "chiffres": chiffres,
        "parametres": parametres.urlencode(),
        "filtres_actifs": any(v for v in parametres.values()),
    })


@espace_requis(PHARMACIE)
def stock_creer(request):
    form = MedicamentForm(request.POST if request.method == "POST" else None, pharmacie=pharmacie_de(request.user))
    if request.method == "POST" and form.is_valid():
        medicament = form.save()
        messages.success(request, f"« {medicament} » a été ajouté au stock.")
        return _redirection(request, "stock")
    return render(request, "pharmacies/medicament_form.html", {"form": form, "medicament": None})


@espace_requis(PHARMACIE)
def stock_modifier(request, pk):
    medicament = _mon_medicament(request, pk)
    form = MedicamentForm(request.POST if request.method == "POST" else None, instance=medicament, pharmacie=medicament.pharmacie)
    if request.method == "POST" and form.is_valid():
        medicament = form.save()
        messages.success(request, f"« {medicament} » a été mis à jour" + (" : il est maintenant en rupture." if medicament.est_en_rupture else "."))
        return _redirection(request, "stock")
    return render(request, "pharmacies/medicament_form.html", {"form": form, "medicament": medicament})


@espace_requis(PHARMACIE)
def stock_supprimer(request, pk):
    """GET : demande de confirmation ; POST : suppression (le médicament n'est plus référencé dans cette pharmacie)."""
    medicament = _mon_medicament(request, pk)
    if request.method == "POST":
        nom = str(medicament)
        medicament.delete()
        messages.success(request, f"« {nom} » a été retiré du stock.")
        return _redirection(request, "stock")
    return render(request, "pharmacies/medicament_supprimer.html", {"medicament": medicament})
