from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("inscription/", views.inscription, name="inscription"),
    path("connexion/", views.ConnexionView.as_view(), name="connexion"),
    path("deconnexion/", views.DeconnexionView.as_view(), name="deconnexion"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("profil/", views.profil, name="profil"),
    path("medecins/", views.liste_medecins, name="medecins"),
    path("medecins/<str:medecin_id>/symptomes/", views.declarer_symptomes, name="symptomes"),
    path("triage/<str:pk>/", views.resultat, name="resultat"),
    path("triage/<str:pk>/annuler/", views.annuler, name="annuler"),
    path("triage/<str:pk>/transferer/<str:medecin_id>/", views.transferer, name="transferer"),
    path("test/file-medecin/<str:medecin_id>/", views.file_medecin_test, name="file_medecin_test"),
]
