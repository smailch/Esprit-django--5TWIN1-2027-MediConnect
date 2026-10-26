import django.db.models.deletion
import django_mongodb_backend.fields
import medecins.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("patients", "0011_lecture_texte_modele"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlageHoraire",
            fields=[
                ("id", django_mongodb_backend.fields.ObjectIdAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jour", models.PositiveSmallIntegerField()),
                ("debut", models.PositiveSmallIntegerField()),
                ("fin", models.PositiveSmallIntegerField()),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Medecin",
            fields=[
                ("id", django_mongodb_backend.fields.ObjectIdAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(help_text="Identifiant stable repris par les demandes (ex. m1).", unique=True)),
                ("specialite", models.CharField(max_length=100)),
                ("ville", models.CharField(max_length=100)),
                ("telephone", models.CharField(blank=True, max_length=20)),
                ("numero_ordre", models.CharField(blank=True, max_length=50, verbose_name="Numéro d'ordre")),
                ("disponible", models.BooleanField(default=True, help_text="Décochez pour fermer la prise de rendez-vous (congés, absence).")),
                ("presentation", models.TextField(blank=True)),
                ("plages", django_mongodb_backend.fields.EmbeddedModelArrayField(blank=True, default=list, embedded_model=medecins.models.PlageHoraire)),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="medecin", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "médecin",
                "verbose_name_plural": "médecins",
                "ordering": ["user__last_name", "user__first_name"],
            },
        ),
        migrations.CreateModel(
            name="Prescription",
            fields=[
                ("id", django_mongodb_backend.fields.ObjectIdAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("ordonnance", "Ordonnance"), ("examen", "Examen de laboratoire"), ("soin", "Soin à domicile")], max_length=20)),
                ("contenu", models.TextField()),
                ("cree_le", models.DateTimeField(auto_now_add=True)),
                ("consultation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="actes", to="patients.consultation")),
            ],
            options={
                "verbose_name": "prescription",
                "verbose_name_plural": "prescriptions",
                "ordering": ["type", "cree_le"],
            },
        ),
    ]
