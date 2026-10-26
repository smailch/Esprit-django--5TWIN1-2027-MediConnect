from django.urls import path

from . import views, views_patient

app_name = "infirmiers"

urlpatterns = [
    # Espace patient : demandes de soins à domicile
    path("soins/", views_patient.soins, name="soins"),
    path("soins/nouveau/", views_patient.soin_demander, name="soin_demander"),
    path("soins/<str:pk>/", views_patient.soin, name="soin"),
    path("soins/<str:pk>/modifier/", views_patient.soin_modifier, name="soin_modifier"),
    path("soins/<str:pk>/supprimer/", views_patient.soin_supprimer, name="soin_supprimer"),
    path("soins/<str:pk>/annuler/", views_patient.soin_annuler, name="soin_annuler"),
    # Espace infirmier
    path("inscription/", views.inscription, name="inscription"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("demandes/", views.demandes, name="demandes"),
    path("planning/", views.planning, name="planning"),
    path("historique/", views.historique, name="historique"),
    path("profil/", views.profil, name="profil"),
    path("interventions/<str:pk>/", views.intervention, name="intervention"),
    path("interventions/<str:pk>/accepter/", views.accepter, name="accepter"),
    path("interventions/<str:pk>/replanifier/", views.replanifier, name="replanifier"),
    path("interventions/<str:pk>/compte-rendu/", views.terminer, name="terminer"),
    path("interventions/<str:pk>/annuler/", views.annuler, name="annuler"),
    path("interventions/<str:pk>/liberer/", views.liberer, name="liberer"),
]
