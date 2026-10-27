from django.urls import path

from . import views

app_name = "medecins"

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau_de_bord"),
    path("inscription/", views.inscription, name="inscription"),
    path("en-attente/", views.en_attente, name="en_attente"),
    path("profil/", views.profil, name="profil"),
    path("file/<str:pk>/", views.synthese, name="synthese"),
    path("file/<str:pk>/niveau/", views.requalifier, name="requalifier"),
    path("file/<str:pk>/commencer/", views.commencer, name="commencer"),
    path("file/<str:pk>/visio/", views.visio, name="visio"),
    path("file/<str:pk>/compte-rendu/", views.compte_rendu, name="compte_rendu"),
    path("consultations/", views.consultations, name="consultations"),
    path("consultations/<str:pk>/", views.consultation_detail, name="consultation_detail"),
    path("consultations/<str:pk>/sms/", views.envoyer_sms, name="envoyer_sms"),
    path("consultations/<str:pk>/whatsapp/", views.envoyer_whatsapp_vue, name="envoyer_whatsapp"),
    path("consultations/<str:pk>/courriel/", views.envoyer_courriel_vue, name="envoyer_courriel"),
    path("consultations/<str:pk>/modifier/", views.consultation_modifier, name="consultation_modifier"),
    path("consultations/<str:pk>/supprimer/", views.consultation_supprimer, name="consultation_supprimer"),
]
