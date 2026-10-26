from django.urls import path

from . import views

app_name = "pharmacies"

# Les adresses fixes (ma-pharmacie/, ordonnances/…) passent avant « <pk>/ », qui les capturerait sinon.
urlpatterns = [
    path("", views.pharmacies, name="pharmacies"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("nouvelle/", views.pharmacie_creer, name="pharmacie_creer"),
    path("ma-pharmacie/", views.ma_pharmacie, name="ma_pharmacie"),
    path("stock/", views.stock_liste, name="stock"),
    path("stock/nouveau/", views.stock_creer, name="stock_creer"),
    path("stock/<str:pk>/modifier/", views.stock_modifier, name="stock_modifier"),
    path("stock/<str:pk>/supprimer/", views.stock_supprimer, name="stock_supprimer"),
    path("ordonnances/", views.ordonnances, name="ordonnances"),
    path("ordonnances/nouvelle/<str:consultation_pk>/", views.ordonnance_creer, name="ordonnance_creer"),
    path("ordonnances/<str:pk>/", views.ordonnance_detail, name="ordonnance_detail"),
    path("ordonnances/<str:pk>/modifier/", views.ordonnance_modifier, name="ordonnance_modifier"),
    path("ordonnances/<str:pk>/supprimer/", views.ordonnance_supprimer, name="ordonnance_supprimer"),
    path("ordonnances/<str:pk>/annuler/", views.ordonnance_annuler, name="ordonnance_annuler"),
    path("ordonnances/<str:pk>/transmettre/", views.ordonnance_transmettre, name="ordonnance_transmettre"),
    path("ordonnances/<str:pk>/avancer/", views.ordonnance_avancer, name="ordonnance_avancer"),
    path("ordonnances/<str:pk>/rupture/", views.ordonnance_rupture, name="ordonnance_rupture"),
    path("ordonnances/<str:pk>/substitution/", views.ordonnance_substitution, name="ordonnance_substitution"),
    path("<str:pk>/", views.pharmacie_detail, name="pharmacie_detail"),
    path("<str:pk>/modifier/", views.pharmacie_modifier, name="pharmacie_modifier"),
    path("<str:pk>/supprimer/", views.pharmacie_supprimer, name="pharmacie_supprimer"),
]
