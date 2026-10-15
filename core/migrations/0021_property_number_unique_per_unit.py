from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_property_number_normal_when_disabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='property_number_unique_per_unit',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'When enabled, registering 10 units creates 10 property numbers. '
                    'When disabled, those 10 units are saved once and share a single property number.'
                ),
                verbose_name='Unique property number per unit',
            ),
        ),
    ]
