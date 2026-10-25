import django.core.validators
import django_mongodb_backend.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0010_consultation'),
    ]

    operations = [
        migrations.AddField(
            model_name='triage',
            name='modele_niveau',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='triage',
            name='modele_confiance',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='triage',
            name='modele_mots',
            field=django_mongodb_backend.fields.ArrayField(base_field=models.CharField(max_length=60), blank=True, default=list),
        ),
        migrations.AddField(
            model_name='triage',
            name='modele_releve',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='reglagetriage',
            name='seuil_modele',
            field=models.PositiveSmallIntegerField(default=85, help_text="Le modèle qui lit le texte du patient ne relève l'urgence que s'il est sûr à au moins ce pourcentage.", validators=[django.core.validators.MinValueValidator(50), django.core.validators.MaxValueValidator(99)], verbose_name='Lecture du texte : confiance minimale (%)'),
        ),
    ]
