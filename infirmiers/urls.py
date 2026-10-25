from django.urls import path

from . import views

app_name = "infirmiers"

urlpatterns = [
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
