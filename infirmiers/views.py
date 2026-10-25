import datetime
from itertools import groupby

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404
from patients.models import Mesure

from . import ia_soin
from .forms import AnnulationForm, CompteRenduForm, InscriptionInfirmierForm, PassageForm, ProfilInfirmierForm
from .models import Infirmier, InterventionDomicile, NiveauAlerte, TypeSoin

Statut = InterventionDomicile.Statut


def _infirmier_connecte(request):
    try:
        return request.user.infirmier
    except Infirmier.DoesNotExist:
        raise PermissionDenied("Cet espace est réservé aux infirmiers.")


def _intervention(request, infirmier, pk):
    """Une intervention que cet infirmier a le droit de voir : la sienne, ou une demande de sa zone encore libre."""
    intervention = objet_ou_404(InterventionDomicile.objects.select_related("patient__user", "infirmier__user"), pk=pk)
    if intervention.infirmier_id == infirmier.pk:
        return intervention
    if intervention.statut == Statut.DEMANDEE and intervention.infirmier_id is None and infirmier.dessert(intervention.ville):
        return intervention
    raise Http404("Intervention introuvable.")


def _message_erreur(erreur):
    return " ".join(erreur.messages)


def inscription(request):
    if request.user.is_authenticated:
        return redirect("infirmiers:tableau_de_bord")

    form = InscriptionInfirmierForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Votre compte a été créé. Un administrateur va vérifier votre numéro d'Ordre avant que vous puissiez accepter des soins.")
        return redirect("infirmiers:tableau_de_bord")
    return render(request, "infirmiers/inscription.html", {"form": form})


@login_required
def tableau_de_bord(request):
    infirmier = _infirmier_connecte(request)
    maintenant = timezone.now()
    aujourdhui = timezone.localdate()
    acceptees = sorted(
        InterventionDomicile.objects.de(infirmier).filter(statut=Statut.ACCEPTEE).select_related("patient__user"),
        key=lambda i: i.date_prevue,
    )
    a_cloturer = [i for i in acceptees if i.date_prevue <= maintenant]
    du_jour = [i for i in acceptees if i.date_prevue > maintenant and timezone.localdate(i.date_prevue) == aujourdhui]
    a_venir = [i for i in acceptees if timezone.localdate(i.date_prevue) > aujourdhui]
    debut_mois = timezone.make_aware(datetime.datetime.combine(aujourdhui.replace(day=1), datetime.time.min))
    realisees_mois = InterventionDomicile.objects.de(infirmier).filter(statut=Statut.REALISEE, realisee_le__gte=debut_mois).count()
    demandes = InterventionDomicile.objects.demandes_pour(infirmier)
    alertes_recentes = sorted(
        InterventionDomicile.objects.de(infirmier).filter(
            statut=Statut.REALISEE,
            niveau_alerte__in=[NiveauAlerte.SIGNALER, NiveauAlerte.SURVEILLER],
            realisee_le__gte=maintenant - datetime.timedelta(days=7),
        ).select_related("patient__user"),
        key=lambda i: (i.niveau_alerte != NiveauAlerte.SIGNALER, -i.realisee_le.timestamp()),
    )
    return render(request, "infirmiers/tableau_de_bord.html", {
        "infirmier": infirmier,
        "alertes_recentes": alertes_recentes,
        "a_cloturer": a_cloturer,
        "du_jour": du_jour,
        "a_venir": a_venir[:5],
        "kpis": {
            "demandes": demandes.count(),
            "du_jour": len(du_jour),
            "a_venir": len(a_venir),
            "realisees_mois": realisees_mois,
        },
    })


@login_required
def demandes(request):
    """Demandes en attente dans les villes de l'infirmier, filtrables par ville et par soin."""
    infirmier = _infirmier_connecte(request)
    villes = infirmier.villes_desservies
    soins_possibles = [(v, l) for v, l in TypeSoin.choices if infirmier.pratique(v)]
    ville = request.GET.get("ville", "")
    soin = request.GET.get("soin", "")

    liste = InterventionDomicile.objects.demandes_pour(infirmier).select_related("patient__user")
    if ville in villes:
        liste = liste.filter(ville__iexact=ville)
    else:
        ville = ""
    if soin in dict(soins_possibles):
        liste = liste.filter(type_soin=soin)
    else:
        soin = ""
    liste = sorted(liste, key=lambda i: (i.date_souhaitee, i.cree_le))
    return render(request, "infirmiers/demandes.html", {
        "infirmier": infirmier,
        "demandes": liste,
        "villes": villes,
        "soins": soins_possibles,
        "filtre": {"ville": ville, "soin": soin},
        "aujourdhui": timezone.localdate(),
    })


@login_required
def planning(request):
    """Interventions acceptées, groupées par jour de passage."""
    infirmier = _infirmier_connecte(request)
    acceptees = sorted(
        InterventionDomicile.objects.de(infirmier).filter(statut=Statut.ACCEPTEE).select_related("patient__user"),
        key=lambda i: i.date_prevue,
    )
    jours = [
        {"jour": jour, "interventions": list(groupe)}
        for jour, groupe in groupby(acceptees, key=lambda i: timezone.localdate(i.date_prevue))
    ]
    return render(request, "infirmiers/planning.html", {"jours": jours, "aujourdhui": timezone.localdate()})


@login_required
def historique(request):
    infirmier = _infirmier_connecte(request)
    closes = InterventionDomicile.objects.de(infirmier).filter(statut__in=[Statut.REALISEE, Statut.ANNULEE]).select_related("patient__user")
    closes = sorted(closes, key=lambda i: i.realisee_le or i.annulee_le or i.modifie_le, reverse=True)
    return render(request, "infirmiers/historique.html", {"interventions": closes})


@login_required
def intervention(request, pk):
    infirmier = _infirmier_connecte(request)
    intervention = _intervention(request, infirmier, pk)
    est_la_mienne = intervention.infirmier_id == infirmier.pk
    contexte = {"intervention": intervention, "infirmier": infirmier, "est_la_mienne": est_la_mienne}
    if est_la_mienne:
        # Le patient n'est identifié en détail qu'une fois la demande acceptée.
        contexte["allergies"] = [a for a in intervention.patient.allergies.all() if a.active]
    elif intervention.statut == Statut.DEMANDEE:
        contexte["form"] = PassageForm(intervention=intervention)
    return render(request, "infirmiers/intervention.html", contexte)


@login_required
@require_POST
def accepter(request, pk):
    infirmier = _infirmier_connecte(request)
    intervention = _intervention(request, infirmier, pk)
    form = PassageForm(request.POST, intervention=intervention)
    if form.is_valid():
        try:
            intervention.accepter(infirmier, form.cleaned_data["date_prevue"])
        except ValidationError as erreur:
            messages.error(request, _message_erreur(erreur))
            return redirect("infirmiers:intervention", pk=pk)
        # Mise à jour conditionnelle : si un collègue a accepté entre-temps, rien n'est écrasé.
        prises = InterventionDomicile.objects.filter(pk=intervention.pk, statut=Statut.DEMANDEE, infirmier__isnull=True).update(
            infirmier=infirmier, date_prevue=intervention.date_prevue, acceptee_le=intervention.acceptee_le,
            statut=Statut.ACCEPTEE, modifie_le=timezone.now(),
        )
        if not prises:
            messages.error(request, "Un autre infirmier vient d'accepter cette demande.")
            return redirect("infirmiers:demandes")
        messages.success(request, f"Demande acceptée : passage prévu le {timezone.localtime(intervention.date_prevue):%d/%m/%Y à %H:%M}.")
        return redirect("infirmiers:intervention", pk=pk)
    return render(request, "infirmiers/intervention.html", {"intervention": intervention, "infirmier": infirmier, "est_la_mienne": False, "form": form})


def _mon_intervention(request, pk):
    infirmier = _infirmier_connecte(request)
    intervention = _intervention(request, infirmier, pk)
    if intervention.infirmier_id != infirmier.pk:
        raise Http404("Intervention introuvable.")
    return infirmier, intervention


@login_required
def replanifier(request, pk):
    _, intervention = _mon_intervention(request, pk)
    if intervention.statut != Statut.ACCEPTEE:
        messages.error(request, "Cette intervention ne peut plus être replanifiée.")
        return redirect("infirmiers:intervention", pk=pk)
    form = PassageForm(request.POST if request.method == "POST" else None, intervention=intervention)
    if request.method == "POST" and form.is_valid():
        try:
            intervention.replanifier(form.cleaned_data["date_prevue"])
        except ValidationError as erreur:
            form.add_error(None, _message_erreur(erreur))
        else:
            intervention.save()
            messages.success(request, "Le passage a été déplacé.")
            return redirect("infirmiers:intervention", pk=pk)
    return render(request, "infirmiers/replanifier.html", {"intervention": intervention, "form": form})


_MESURES_SUIVIES = {
    Mesure.Type.TEMPERATURE: "temperature",
    Mesure.Type.TENSION: "tension_systolique",
    Mesure.Type.FREQUENCE: "frequence_cardiaque",
    Mesure.Type.SATURATION: "saturation_oxygene",
}


def _historique(intervention):
    """Relevés précédents du patient, du plus ancien au plus récent : constantes des passages infirmiers
    déjà terminés et mesures saisies par le patient lui-même."""
    releves = [
        (i.realisee_le, i.releves())
        for i in InterventionDomicile.objects.filter(patient=intervention.patient, statut=Statut.REALISEE).exclude(pk=intervention.pk)
        if i.realisee_le and i.constantes is not None
    ]
    for m in Mesure.objects.filter(patient=intervention.patient, type__in=list(_MESURES_SUIVIES)):
        valeurs = {_MESURES_SUIVIES[m.type]: m.valeur}
        if m.type == Mesure.Type.TENSION and m.valeur2 is not None:
            valeurs["tension_diastolique"] = m.valeur2
        releves.append((m.mesure_le, valeurs))
    return [valeurs for _, valeurs in sorted(releves, key=lambda r: r[0])]


def _analyser(intervention, infirmier, texte, constantes=None):
    user = intervention.patient.user
    return ia_soin.analyser(
        texte,
        constantes=constantes,
        historique=_historique(intervention),
        noms_patient=(user.first_name, user.last_name),
        identifiant=f"infirmier:{infirmier.pk}",
    )


def _valeur_de_champ(valeur):
    return f"{valeur:g}"


@login_required
def terminer(request, pk):
    """« Analyser » : lit la note (règles + IA), pré-remplit les constantes vides et montre les alertes, sans rien
    enregistrer. « Enregistrer » : analyse la version finale (constantes relues par l'infirmier) et clôt l'intervention."""
    infirmier, intervention = _mon_intervention(request, pk)
    if intervention.statut != Statut.ACCEPTEE:
        messages.error(request, "Le compte rendu ne peut être saisi que pour une intervention acceptée.")
        return redirect("infirmiers:intervention", pk=pk)

    analyse, preremplis = None, []
    if request.method == "POST" and request.POST.get("action") == "analyser":
        analyse = _analyser(intervention, infirmier, request.POST.get("compte_rendu", ""))
        initial = {nom: request.POST.get(nom, "") for nom in CompteRenduForm.base_fields}
        for nom, (valeur, _, _) in analyse.constantes.items():
            if not initial.get(nom, "").strip():
                initial[nom] = _valeur_de_champ(valeur)
                preremplis.append(nom)
        form = CompteRenduForm(initial=initial)
    else:
        form = CompteRenduForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            constantes = form.constantes()
            analyse = _analyser(
                intervention, infirmier, form.cleaned_data["compte_rendu"],
                constantes={n: form.cleaned_data[n] for n in CompteRenduForm.CONSTANTES},
            )
            try:
                intervention.terminer(form.cleaned_data["compte_rendu"], constantes, form.cleaned_data["realisee_le"], analyse=analyse)
            except ValidationError as erreur:
                form.add_error(None, _message_erreur(erreur))
            else:
                intervention.save()
                if analyse.niveau == NiveauAlerte.SIGNALER:
                    messages.warning(request, "Compte rendu enregistré. Des signes d'alerte sont à signaler au médecin.")
                else:
                    messages.success(request, "Compte rendu enregistré : l'intervention est terminée.")
                return redirect("infirmiers:intervention", pk=pk)
    return render(request, "infirmiers/compte_rendu.html", {
        "intervention": intervention,
        "form": form,
        "analyse": analyse,
        "preremplis": [form[n].label for n in preremplis],
    })


@login_required
def annuler(request, pk):
    """GET : demande le motif ; POST : annule."""
    _, intervention = _mon_intervention(request, pk)
    if not intervention.est_modifiable:
        messages.error(request, "Cette intervention est déjà close.")
        return redirect("infirmiers:intervention", pk=pk)
    form = AnnulationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            intervention.annuler(form.cleaned_data["motif"])
        except ValidationError as erreur:
            form.add_error(None, _message_erreur(erreur))
        else:
            intervention.save()
            messages.success(request, "L'intervention a été annulée.")
            return redirect("infirmiers:planning")
    return render(request, "infirmiers/annuler.html", {"intervention": intervention, "form": form})


@login_required
@require_POST
def liberer(request, pk):
    _, intervention = _mon_intervention(request, pk)
    try:
        intervention.liberer()
    except ValidationError as erreur:
        messages.error(request, _message_erreur(erreur))
        return redirect("infirmiers:intervention", pk=pk)
    intervention.save()
    messages.success(request, "Vous vous êtes désisté : la demande est de nouveau proposée aux infirmiers de la zone.")
    return redirect("infirmiers:planning")


@login_required
def profil(request):
    infirmier = _infirmier_connecte(request)
    form = ProfilInfirmierForm(request.POST if request.method == "POST" else None, instance=infirmier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votre profil a été enregistré.")
        return redirect("infirmiers:profil")
    return render(request, "infirmiers/profil.html", {"form": form, "infirmier": infirmier})
