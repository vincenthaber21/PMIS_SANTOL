from django.conf import settings as django_settings
from django.db import migrations, models


def seed_par_defaults(apps, schema_editor):
    SiteSettings = apps.get_model('core', 'SiteSettings')
    site, _ = SiteSettings.objects.get_or_create(pk=1)
    updated = False
    if not (site.lgu_province or '').strip():
        site.lgu_province = getattr(django_settings, 'LGU_PROVINCE', 'LA UNION')
        updated = True
    defaults = {
        'par_received_by_name': '',
        'par_received_by_position': '',
        'par_received_from_name': '',
        'par_received_from_position': '',
    }
    for field, value in defaults.items():
        if not getattr(site, field):
            setattr(site, field, value)
            updated = True
    if updated:
        site.save()


def unseed_par_defaults(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_sitesettings_ics_supplier_block'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='lgu_province',
            field=models.CharField(
                default='LA UNION',
                help_text='Province name printed on PAR headers (e.g. LA UNION).',
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='par_received_by_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Printed name on PAR “Received by” signature block. Leave blank to use the end-user on each PAR.',
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='par_received_by_position',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Position/office on PAR “Received by” signature block (e.g. Operations).',
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='par_received_from_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Printed name on PAR “Received from” signature block. Leave blank to use the custodian on each PAR.',
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='par_received_from_position',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Position/office on PAR “Received from” signature block (e.g. Administration).',
                max_length=200,
            ),
        ),
        migrations.RunPython(seed_par_defaults, unseed_par_defaults),
    ]
