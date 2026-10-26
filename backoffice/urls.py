from django.urls import path

from . import views, views_comptes

app_name = "backoffice"

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau_de_bord"),
    path("rendez-vous/", views.rendez_vous, name="rendez_vous"),
    path("file-attente/", views.file_attente, name="file_attente"),
    path("parametres/", views.parametres, name="parametres"),
    path("modele-texte/", views.modele_texte, name="modele_texte"),
    path("rendez-vous/<str:pk>/", views.rendez_vous_detail, name="rendez_vous_detail"),
    path("patients/", views.patients, name="patients"),
    path("patients/export/", views.patients_exporter, name="patients_exporter"),
    path("patients/<str:pk>/desactiver/", views.patient_desactiver, name="patient_desactiver"),
    path("patients/<str:pk>/reactiver/", views.patient_reactiver, name="patient_reactiver"),
    path("patients/<str:pk>/", views.patient_detail, name="patient_detail"),
    path("medecins/", views.medecins, name="medecins"),
    path("medecins/<str:pk>/valider/", views.medecin_valider, name="medecin_valider"),
    path("medecins/<str:pk>/retirer/", views.medecin_retirer, name="medecin_retirer"),
    path("medecins/<str:pk>/desactiver/", views.medecin_desactiver, name="medecin_desactiver"),
    path("medecins/<str:pk>/reactiver/", views.medecin_reactiver, name="medecin_reactiver"),
    path("medecins/<str:pk>/disponibilite/", views.medecin_disponibilite, name="medecin_disponibilite"),
    path("medecins/<str:pk>/", views.medecin_detail, name="medecin_detail"),
    path("symptomes/", views.symptomes, name="symptomes"),
    path("comptes/", views_comptes.ComptesView.as_view(), name="comptes"),
    path("comptes/journal/", views_comptes.JournalConnexionsView.as_view(), name="journal_connexions"),
    path("comptes/<str:pk>/<str:action>/", views_comptes.CompteActionView.as_view(), name="compte_action"),
]
