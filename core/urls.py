from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("connexion/", views.ConnexionView.as_view(), name="connexion"),
    path("deconnexion/", views.DeconnexionView.as_view(), name="deconnexion"),
    path("mot-de-passe/", views.ChangementMotDePasseView.as_view(), name="mot_de_passe"),
    path("mot-de-passe-oublie/", views.ReinitialisationView.as_view(), name="reinitialisation"),
    path("mot-de-passe-oublie/envoye/", views.ReinitialisationEnvoyeeView.as_view(), name="reinitialisation_envoyee"),
    path("reinitialisation/<uidb64>/<token>/", views.ReinitialisationConfirmationView.as_view(), name="reinitialisation_confirmation"),
    path("reinitialisation/terminee/", views.ReinitialisationTermineeView.as_view(), name="reinitialisation_terminee"),
]
