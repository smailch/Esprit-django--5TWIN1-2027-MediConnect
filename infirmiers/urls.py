from django.urls import path

from . import views, views_admin, views_patient

app_name = "infirmiers"

urlpatterns = [
    # Espace patient : demandes de soins à domicile
    path("soins/", views_patient.soins, name="soins"),
    path("soins/nouveau/", views_patient.soin_demander, name="soin_demander"),
    path("soins/<str:pk>/", views_patient.soin, name="soin"),
    path("soins/<str:pk>/modifier/", views_patient.soin_modifier, name="soin_modifier"),
    path("soins/<str:pk>/supprimer/", views_patient.soin_supprimer, name="soin_supprimer"),
    path("soins/<str:pk>/annuler/", views_patient.soin_annuler, name="soin_annuler"),
    path("soins/<str:pk>/serie/retirer/", views_patient.soin_serie_retirer, name="soin_serie_retirer"),
    # Espace administrateur : alertes des comptes rendus
    path("alertes/", views_admin.alertes, name="alertes"),
    path("alertes/<str:pk>/", views_admin.alerte, name="alerte"),
    path("alertes/<str:pk>/traiter/", views_admin.alerte_traiter, name="alerte_traiter"),
    # Espace infirmier
    path("inscription/", views.inscription, name="inscription"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("demandes/", views.demandes, name="demandes"),
    path("planning/", views.planning, name="planning"),
    path("planning/<str:jour>/tournee/", views.tournee, name="tournee"),
    path("historique/", views.historique, name="historique"),
    path("profil/", views.profil, name="profil"),
    path("series/<str:cle>/", views.serie, name="serie"),
    path("interventions/<str:pk>/", views.intervention, name="intervention"),
    path("interventions/<str:pk>/accepter/", views.accepter, name="accepter"),
    path("interventions/<str:pk>/replanifier/", views.replanifier, name="replanifier"),
    path("interventions/<str:pk>/compte-rendu/", views.terminer, name="terminer"),
    path("interventions/<str:pk>/annuler/", views.annuler, name="annuler"),
    path("interventions/<str:pk>/liberer/", views.liberer, name="liberer"),
]
