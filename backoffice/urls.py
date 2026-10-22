from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau_de_bord"),
    path("rendez-vous/", views.rendez_vous, name="rendez_vous"),
    path("file-attente/", views.file_attente, name="file_attente"),
    path("parametres/", views.parametres, name="parametres"),
    path("rendez-vous/<str:pk>/", views.rendez_vous_detail, name="rendez_vous_detail"),
    path("patients/", views.patients, name="patients"),
    path("patients/<str:pk>/", views.patient_detail, name="patient_detail"),
    path("symptomes/", views.symptomes, name="symptomes"),
]
