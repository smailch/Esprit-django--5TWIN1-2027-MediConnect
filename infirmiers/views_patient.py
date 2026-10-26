"""Espace patient : demander un soin à domicile et suivre ses demandes.

Les pages utilisent le cadre de l'espace patient (patients/layout.html) mais restent dans l'app infirmiers,
qui possède le modèle InterventionDomicile."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone

from core.utils import objet_ou_404
from patients.models import Patient

from . import notifications
from .forms import AnnulationForm, DemandeSoinForm
from .models import Infirmier, InterventionDomicile

Statut = InterventionDomicile.Statut


def _patient_connecte(request):
    try:
        return request.user.patient
    except Patient.DoesNotExist:
        raise PermissionDenied("Cet espace est réservé aux patients.")


def _ma_demande(request, pk):
    patient = _patient_connecte(request)
    return objet_ou_404(InterventionDomicile.objects.select_related("infirmier__user", "consultation"), pk=pk, patient=patient)


def infirmiers_disponibles(intervention):
    """Infirmiers validés et disponibles qui peuvent accepter cette demande (zone et soin)."""
    return [
        i for i in Infirmier.objects.select_related("user").filter(disponible=True)
        if i.est_valide and i.dessert(intervention.ville) and i.pratique(intervention.type_soin)
    ]


@login_required
def soins(request):
    patient = _patient_connecte(request)
    toutes = list(InterventionDomicile.objects.filter(patient=patient).select_related("infirmier__user"))
    en_cours = sorted((i for i in toutes if i.est_modifiable), key=lambda i: (i.date_prevue is None, i.date_prevue or i.cree_le))
    closes = sorted((i for i in toutes if not i.est_modifiable), key=lambda i: i.modifie_le, reverse=True)
    return render(request, "infirmiers/patient/soins.html", {"en_cours": en_cours, "closes": closes})


@login_required
def soin_demander(request):
    patient = _patient_connecte(request)
    form = DemandeSoinForm(request.POST if request.method == "POST" else None, patient=patient)
    if request.method == "POST" and form.is_valid():
        demande = form.save()
        nombre = len(infirmiers_disponibles(demande))
        quoi = "Votre demande"
        if demande.serie:
            dernier = form.series[-1].date_souhaitee
            quoi = f"Votre série de {len(form.series)} passages (du {demande.date_souhaitee:%d/%m} au {dernier:%d/%m})"
        if nombre:
            messages.success(request, f"{quoi} a été envoyée à {nombre} infirmier(s) de {demande.ville}.")
        else:
            messages.warning(request, f"{quoi} est enregistrée, mais aucun infirmier ne se déplace encore à {demande.ville} pour ce soin.")
        return redirect("infirmiers:soin", pk=demande.pk)
    return render(request, "infirmiers/patient/soin_form.html", {"form": form, "demande": None})


@login_required
def soin(request, pk):
    demande = _ma_demande(request, pk)
    contexte = {"demande": demande}
    if demande.serie:
        contexte["serie"] = sorted(
            InterventionDomicile.objects.filter(patient=demande.patient, serie=demande.serie).select_related("infirmier__user"),
            key=lambda i: i.rang_serie or 0,
        )
        contexte["serie_retirables"] = sum(1 for i in contexte["serie"] if i.statut == Statut.DEMANDEE)
    if demande.statut == Statut.DEMANDEE:
        contexte["nombre_infirmiers"] = len(infirmiers_disponibles(demande))
    return render(request, "infirmiers/patient/soin.html", contexte)


@login_required
def soin_modifier(request, pk):
    demande = _ma_demande(request, pk)
    if demande.statut != Statut.DEMANDEE:
        messages.error(request, "Un infirmier a déjà accepté cette demande : elle ne peut plus être modifiée. Vous pouvez l'annuler.")
        return redirect("infirmiers:soin", pk=pk)
    form = DemandeSoinForm(request.POST if request.method == "POST" else None, instance=demande, patient=demande.patient)
    if request.method == "POST" and form.is_valid():
        # Mise à jour seulement si personne ne l'a acceptée entre-temps.
        champs = {nom: getattr(form.instance, nom) for nom in form.Meta.fields}  # valeurs nettoyées par le modèle
        champs["modifie_le"] = timezone.now()
        modifiees = InterventionDomicile.objects.filter(pk=demande.pk, statut=Statut.DEMANDEE, infirmier__isnull=True).update(**champs)
        if not modifiees:
            messages.error(request, "Un infirmier vient d'accepter cette demande : vos modifications n'ont pas été enregistrées.")
        else:
            messages.success(request, "Votre demande a été modifiée.")
        return redirect("infirmiers:soin", pk=pk)
    return render(request, "infirmiers/patient/soin_form.html", {"form": form, "demande": demande})


@login_required
def soin_supprimer(request, pk):
    """Retirer une demande qu'aucun infirmier n'a encore acceptée. GET : confirmation ; POST : suppression."""
    demande = _ma_demande(request, pk)
    if demande.statut != Statut.DEMANDEE:
        messages.error(request, "Cette demande a déjà été prise en charge : annulez-la plutôt, l'infirmier sera informé.")
        return redirect("infirmiers:soin", pk=pk)
    if request.method == "POST":
        supprimees, _ = InterventionDomicile.objects.filter(pk=demande.pk, statut=Statut.DEMANDEE, infirmier__isnull=True).delete()
        if supprimees:
            messages.success(request, "Votre demande a été retirée.")
            return redirect("infirmiers:soins")
        messages.error(request, "Un infirmier vient d'accepter cette demande : annulez-la plutôt.")
        return redirect("infirmiers:soin", pk=pk)
    return render(request, "infirmiers/patient/soin_supprimer.html", {"demande": demande})


@login_required
def soin_annuler(request, pk):
    """Annuler une demande acceptée (le rendez-vous avec l'infirmier tombe), avec un motif."""
    demande = _ma_demande(request, pk)
    if demande.statut != Statut.ACCEPTEE:
        return redirect("infirmiers:soin_supprimer" if demande.statut == Statut.DEMANDEE else "infirmiers:soin", pk=pk)
    form = AnnulationForm(request.POST if request.method == "POST" else None)
    form.fields["motif"].help_text = "Ex. hospitalisation, soin plus nécessaire, absent à cette date. L'infirmier le verra."
    if request.method == "POST" and form.is_valid():
        try:
            demande.annuler(form.cleaned_data["motif"])
        except ValidationError as erreur:
            form.add_error(None, " ".join(erreur.messages))
        else:
            demande.save()
            lien = request.build_absolute_uri(reverse("infirmiers:intervention", args=[demande.pk]))
            if notifications.annule_par_le_patient(demande, lien):
                messages.success(request, "Le passage de l'infirmier est annulé : il a été prévenu par e-mail.")
            else:
                messages.success(request, "Le passage de l'infirmier est annulé.")
            return redirect("infirmiers:soin", pk=pk)
    return render(request, "infirmiers/patient/soin_annuler.html", {"demande": demande, "form": form})


@login_required
@require_POST
def soin_serie_retirer(request, pk):
    """Retire d'un coup les passages de la série qu'aucun infirmier n'a encore acceptés ; les autres restent prévus."""
    demande = _ma_demande(request, pk)
    if not demande.serie:
        return redirect("infirmiers:soin", pk=pk)
    retires = 0
    for passage in InterventionDomicile.objects.filter(patient=demande.patient, serie=demande.serie, statut=Statut.DEMANDEE, infirmier__isnull=True):
        passage.delete()
        retires += 1
    restants = InterventionDomicile.objects.filter(patient=demande.patient, serie=demande.serie).order_by("date_souhaitee").first()
    messages.success(request, f"{retires} passage(s) non accepté(s) retiré(s) de la série.")
    return redirect("infirmiers:soin", pk=restants.pk) if restants else redirect("infirmiers:soins")
