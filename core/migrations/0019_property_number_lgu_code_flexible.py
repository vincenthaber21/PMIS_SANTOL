from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_countdown_days_schedule'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesettings',
            name='property_number_lgu_code',
            field=models.CharField(
                default='1042',
                help_text=(
                    'Code printed on inventory tags, and used as the property-number prefix when '
                    'legacy mode is enabled. Use a numeric code (0621) or a custom prefix (LGU-SANTOL).'
                ),
                max_length=40,
                verbose_name='Property number LGU code',
            ),
        ),
        migrations.AlterField(
            model_name='sitesettings',
            name='property_number_use_legacy_lgu_code',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When enabled, auto-generated property numbers start with the LGU code above '
                    '(e.g. 0621-201-2027-PR-0001 or LGU-SANTOL-201-2027-PR-0001). When disabled, '
                    'they start with LGU-{Municipality} from PAR Header '
                    '(e.g. LGU-SANTOL-201-2027-PR-0001).'
                ),
                verbose_name='Use legacy numeric LGU code for property numbers',
            ),
        ),
    ]
