import datetime
from itertools import groupby

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import objet_ou_404

from . import dossier, ia_soin, notifications, tournee as calcul_tournee
from .forms import AnnulationForm, CompteRenduForm, HeureSerieForm, InscriptionInfirmierForm, PassageForm, ProfilInfirmierForm
from .models import Infirmier, InterventionDomicile, NiveauAlerte, TypeSoin, passage_en_conflit, prochain_creneau_libre

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


def _prochain_quart_d_heure():
    maintenant = timezone.localtime().replace(second=0, microsecond=0)
    return maintenant + datetime.timedelta(minutes=15 - maintenant.minute % 15)


def _conflit_de_planning(infirmier, quand, exclure=None):
    """Message si l'infirmier a déjà un passage à moins de 30 minutes de `quand`, sinon None."""
    autres = InterventionDomicile.objects.passages_autour(infirmier, quand, exclure)
    conflit = passage_en_conflit(quand, autres)
    if conflit is None:
        return None
    libre = timezone.localtime(prochain_creneau_libre(quand, autres))
    return (
        f"Vous avez déjà un passage à {timezone.localtime(conflit):%H:%M} ce jour-là. "
        f"Prochain créneau libre : {libre:%d/%m à %H:%M}."
    )


def lien_patient(request, intervention):
    """Adresse complète de la demande dans l'espace patient (pour les e-mails)."""
    return request.build_absolute_uri(reverse("infirmiers:soin", args=[intervention.pk]))


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
        "demandes": _regrouper_series(liste),
        "villes": villes,
        "soins": soins_possibles,
        "filtre": {"ville": ville, "soin": soin},
        "aujourdhui": timezone.localdate(),
    })


def _regrouper_series(demandes):
    """Une ligne par demande, sauf les passages d'une même série, réunis sur une seule ligne (dans l'ordre)."""
    lignes, vues = [], set()
    for demande in demandes:
        if not demande.serie:
            lignes.append({"premier": demande, "serie": None})
        elif demande.serie not in vues:
            vues.add(demande.serie)
            lignes.append({"premier": demande, "serie": [d for d in demandes if d.serie == demande.serie]})
    return lignes


def _passages_de_serie(infirmier, cle):
    """Passages d'une série que cet infirmier peut voir : encore libres dans sa zone, ou déjà à lui."""
    passages = sorted(
        InterventionDomicile.objects.filter(serie=cle).select_related("patient__user", "infirmier__user"),
        key=lambda i: i.rang_serie or 0,
    )
    visibles = [
        p for p in passages
        if p.infirmier_id == infirmier.pk or (p.statut == Statut.DEMANDEE and p.infirmier_id is None and infirmier.dessert(p.ville))
    ]
    if not visibles:
        raise Http404("Série introuvable.")
    return passages, visibles


@login_required
def serie(request, cle):
    infirmier = _infirmier_connecte(request)
    passages, visibles = _passages_de_serie(infirmier, cle)
    libres = [p for p in visibles if p.statut == Statut.DEMANDEE]
    form = HeureSerieForm(request.POST if request.method == "POST" else None, premier=passages[0])
    if request.method == "POST" and form.is_valid() and libres:
        erreurs, plan = [], []
        for passage in libres:
            quand = timezone.make_aware(datetime.datetime.combine(passage.date_souhaitee, form.cleaned_data["heure"]))
            if quand < timezone.now():
                erreurs.append(f"{passage.date_souhaitee:%d/%m} : l'heure est déjà passée")
                continue
            if conflit := _conflit_de_planning(infirmier, quand):
                erreurs.append(f"{passage.date_souhaitee:%d/%m} : {conflit}")
                continue
            try:
                passage.accepter(infirmier, quand)
            except ValidationError as erreur:
                erreurs.append(f"{passage.date_souhaitee:%d/%m} : {_message_erreur(erreur)}")
                continue
            plan.append(passage)
        if erreurs:  # tout ou rien : une série à trous ne servirait pas le patient
            for erreur in erreurs:
                form.add_error(None, erreur)
        else:
            acceptes = [
                p for p in plan
                if InterventionDomicile.objects.filter(pk=p.pk, statut=Statut.DEMANDEE, infirmier__isnull=True).update(
                    infirmier=infirmier, date_prevue=p.date_prevue, acceptee_le=p.acceptee_le, statut=Statut.ACCEPTEE, modifie_le=timezone.now(),
                )
            ]
            if acceptes:
                notifications.serie_acceptee(acceptes, lien_patient(request, acceptes[0]))
            pris = len(plan) - len(acceptes)
            messages.success(request, f"{len(acceptes)} passage(s) de la série accepté(s) à {form.cleaned_data['heure']:%H:%M}."
                             + (f" {pris} venaient d'être pris par un collègue." if pris else ""))
            return redirect("infirmiers:planning")
    return render(request, "infirmiers/serie.html", {
        "infirmier": infirmier, "passages": passages, "libres": libres, "premier": passages[0], "form": form,
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
    for j in jours:
        j["optimisable"] = len(j["interventions"]) >= 2 and j["jour"] >= timezone.localdate()
    return render(request, "infirmiers/planning.html", {"jours": jours, "aujourdhui": timezone.localdate()})


def _passages_du_jour(infirmier, jour):
    debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
    return list(InterventionDomicile.objects.de(infirmier).filter(
        statut=Statut.ACCEPTEE, date_prevue__gte=debut, date_prevue__lt=debut + datetime.timedelta(days=1),
    ).select_related("patient__user"))


def _prioritaires(passages):
    """Passages dont le patient avait une alerte « à signaler » à son dernier compte rendu."""
    derniers = {}
    for i in InterventionDomicile.objects.filter(patient_id__in=[p.patient_id for p in passages], statut=Statut.REALISEE):
        if i.realisee_le and (i.patient_id not in derniers or i.realisee_le > derniers[i.patient_id].realisee_le):
            derniers[i.patient_id] = i
    return {p.pk for p in passages if p.patient_id in derniers and derniers[p.patient_id].niveau_alerte == NiveauAlerte.SIGNALER}


@login_required
def tournee(request, jour):
    """Propose un ordre de passage qui limite les changements de ville ; l'infirmier l'applique s'il le souhaite."""
    infirmier = _infirmier_connecte(request)
    try:
        jour = datetime.date.fromisoformat(jour)
    except ValueError:
        raise Http404("Date invalide.")
    if jour < timezone.localdate():
        messages.error(request, "Cette journée est passée.")
        return redirect("infirmiers:planning")
    passages = _passages_du_jour(infirmier, jour)
    if len(passages) < 2:
        messages.error(request, "Il faut au moins deux passages ce jour-là pour optimiser la tournée.")
        return redirect("infirmiers:planning")

    actuelle = calcul_tournee.actuelle(passages)
    debut = actuelle.etapes[0][1]
    if jour == timezone.localdate():
        debut = max(debut, _prochain_quart_d_heure())
    prioritaires = _prioritaires(passages)
    proposee = calcul_tournee.proposer(passages, infirmier.ville, debut, prioritaires)

    if request.method == "POST":
        deplaces = 0
        for passage, heure in proposee.etapes:
            if heure == passage.date_prevue:
                continue
            ancien = passage.date_prevue
            try:
                passage.replanifier(heure)
            except ValidationError as erreur:
                messages.error(request, f"{passage.patient} : {_message_erreur(erreur)}")
                continue
            passage.save()
            notifications.passage_fixe(passage, lien_patient(request, passage), ancien=ancien)
            deplaces += 1
        messages.success(request, f"Tournée appliquée : {deplaces} passage(s) déplacé(s), les patients concernés ont été prévenus.")
        return redirect("infirmiers:planning")

    return render(request, "infirmiers/tournee.html", {
        "jour": jour, "actuelle": actuelle, "proposee": proposee, "prioritaires": prioritaires,
        "identique": calcul_tournee.est_identique(actuelle, proposee),
        "gain_villes": actuelle.changements_de_ville - proposee.changements_de_ville,
    })


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
        form = PassageForm(intervention=intervention)
        # L'heure proposée tient compte du planning : jamais sur un passage déjà accepté.
        proposee = max(timezone.make_aware(form.initial["date_prevue"]), _prochain_quart_d_heure())
        autres = InterventionDomicile.objects.passages_autour(infirmier, proposee)
        form.initial["date_prevue"] = prochain_creneau_libre(proposee, autres)
        contexte["form"] = form
    return render(request, "infirmiers/intervention.html", contexte)


@login_required
@require_POST
def accepter(request, pk):
    infirmier = _infirmier_connecte(request)
    intervention = _intervention(request, infirmier, pk)
    form = PassageForm(request.POST, intervention=intervention)
    if form.is_valid() and (conflit := _conflit_de_planning(infirmier, form.cleaned_data["date_prevue"])):
        form.add_error("date_prevue", conflit)
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
        notifications.passage_fixe(intervention, lien_patient(request, intervention))
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
    infirmier, intervention = _mon_intervention(request, pk)
    if intervention.statut != Statut.ACCEPTEE:
        messages.error(request, "Cette intervention ne peut plus être replanifiée.")
        return redirect("infirmiers:intervention", pk=pk)
    form = PassageForm(request.POST if request.method == "POST" else None, intervention=intervention)
    if request.method == "POST" and form.is_valid():
        conflit = _conflit_de_planning(infirmier, form.cleaned_data["date_prevue"], exclure=intervention.pk)
        if conflit:
            form.add_error("date_prevue", conflit)
    if request.method == "POST" and form.is_valid():
        ancien = intervention.date_prevue
        try:
            intervention.replanifier(form.cleaned_data["date_prevue"])
        except ValidationError as erreur:
            form.add_error(None, _message_erreur(erreur))
        else:
            intervention.save()
            if intervention.date_prevue != ancien:
                notifications.passage_fixe(intervention, lien_patient(request, intervention), ancien=ancien)
            messages.success(request, "Le passage a été déplacé.")
            return redirect("infirmiers:intervention", pk=pk)
    return render(request, "infirmiers/replanifier.html", {"intervention": intervention, "form": form})


def _analyser(intervention, infirmier, texte, constantes=None):
    user = intervention.patient.user
    return ia_soin.analyser(
        texte,
        constantes=constantes,
        historique=dossier.historique(intervention),
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
                dossier.enregistrer_mesures(intervention)  # les constantes rejoignent « Mes mesures » du patient
                notifications.compte_rendu_disponible(intervention, lien_patient(request, intervention))
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
            if intervention.date_prevue is not None:  # le patient attendait un passage
                notifications.passage_annule(intervention, lien_patient(request, intervention))
            messages.success(request, "L'intervention a été annulée.")
            return redirect("infirmiers:planning")
    return render(request, "infirmiers/annuler.html", {"intervention": intervention, "form": form})


@login_required
@require_POST
def liberer(request, pk):
    infirmier, intervention = _mon_intervention(request, pk)
    ancien = intervention.date_prevue
    try:
        intervention.liberer()
    except ValidationError as erreur:
        messages.error(request, _message_erreur(erreur))
        return redirect("infirmiers:intervention", pk=pk)
    intervention.save()
    notifications.passage_libere(intervention, lien_patient(request, intervention), infirmier, ancien)
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
