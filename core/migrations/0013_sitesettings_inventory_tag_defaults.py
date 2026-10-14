from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_fix_par_custodian_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='inventory_tag_coa_representative',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    'Default COA Representative shown on printed inventory tags. '
                    'Users can change this value before printing.'
                ),
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='inventory_tag_date_counted',
            field=models.DateField(
                blank=True,
                help_text=(
                    'Default Date:(Counted) shown on printed inventory tags. '
                    'Users can change this value before printing.'
                ),
                null=True,
            ),
        ),
    ]
