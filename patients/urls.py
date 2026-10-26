from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("inscription/", views.inscription, name="inscription"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("profil/", views.profil, name="profil"),
    path("compte/", views.compte, name="compte"),
    path("compte/donnees/", views.compte_exporter, name="compte_exporter"),
    path("dossier/", views.dossier, name="dossier"),
    path("dossier/analyse/", views.analyse, name="analyse_dossier"),
    path("dossier/consultations/", views.consultations, name="consultations"),
    path("ia/", views.ia_consentement, name="ia_consentement"),
    path("allergies/", views.allergies, name="allergies"),
    path("allergies/nouvelle/", views.allergie_creer, name="allergie_creer"),
    path("allergies/<str:pk>/modifier/", views.allergie_modifier, name="allergie_modifier"),
    path("allergies/<str:pk>/supprimer/", views.allergie_supprimer, name="allergie_supprimer"),
    path("mesures/", views.mesures, name="mesures"),
    path("mesures/export/", views.mesures_exporter, name="mesures_exporter"),
    path("mesures/nouvelle/", views.mesure_creer, name="mesure_creer"),
    path("mesures/<str:pk>/modifier/", views.mesure_modifier, name="mesure_modifier"),
    path("mesures/<str:pk>/supprimer/", views.mesure_supprimer, name="mesure_supprimer"),
    path("medecins/", views.liste_medecins, name="medecins"),
    path("orientation/", views.orientation, name="orientation"),
    path("medecins/<str:medecin_id>/symptomes/", views.declarer_symptomes, name="symptomes"),
    path("triage/<str:pk>/", views.resultat, name="resultat"),
    path("triage/<str:pk>/annuler/", views.annuler, name="annuler"),
    path("triage/<str:pk>/creneaux/", views.creneaux, name="creneaux"),
    path("triage/<str:pk>/creneau/retirer/", views.creneau_retirer, name="creneau_retirer"),
    path("triage/<str:pk>/file/", views.rester_dans_la_file, name="rester_dans_la_file"),
    path("triage/<str:pk>/transferer/<str:medecin_id>/", views.transferer, name="transferer"),
    path("test/file-medecin/<str:medecin_id>/", views.file_medecin_test, name="file_medecin_test"),
]
