from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_sitesettings_inventory_tag_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='property_number_use_legacy_lgu_code',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When enabled, auto-generated property numbers use the numeric code above '
                    '(e.g. 0621-201-2027-PR-0001). When disabled, they use LGU-{Municipality} from '
                    'PAR Header (e.g. LGU-Sudipen-201-2027-PR-0001).'
                ),
                verbose_name='Use legacy numeric LGU code for property numbers',
            ),
        ),
        migrations.AlterField(
            model_name='sitesettings',
            name='property_number_lgu_code',
            field=models.CharField(
                default='1042',
                help_text=(
                    'Numeric LGU / school code (e.g. 0621). Used on inventory tags; also used as '
                    'the property-number prefix when legacy mode is enabled below.'
                ),
                max_length=20,
            ),
        ),
    ]
