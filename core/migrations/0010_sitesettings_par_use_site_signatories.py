from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_equipment_property_number_pk'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='par_use_site_signatories',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When enabled, print the names and positions below on every PAR. '
                    'When disabled, use each PAR’s assigned end-user and supply officer instead.'
                ),
                verbose_name='Use site default signatories',
            ),
        ),
    ]
