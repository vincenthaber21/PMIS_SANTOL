from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_property_number_lgu_code_flexible'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesettings',
            name='property_number_use_legacy_lgu_code',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When enabled, auto-generated property numbers start with the LGU code above '
                    '(e.g. LGU-SANTOL-201-2027-PR-0001 or 0621-201-2027-PR-0001). When disabled, '
                    'they use the normal form number (e.g. PAR-201-2027-PR-0001).'
                ),
                verbose_name='Use legacy numeric LGU code for property numbers',
            ),
        ),
        migrations.AlterField(
            model_name='sitesettings',
            name='lgu_municipality',
            field=models.CharField(
                default='SUDIPEN',
                help_text='Municipality name printed on PAR/ICS headers (e.g. SUDIPEN).',
                max_length=100,
            ),
        ),
    ]
