from django.db import migrations, models


def seed_par_header_title(apps, schema_editor):
    SiteSettings = apps.get_model('core', 'SiteSettings')
    site, _ = SiteSettings.objects.get_or_create(pk=1)
    if not (site.par_header_title or '').strip():
        site.par_header_title = 'PROPERTY ACKNOWLEDGEMENT RECEIPT'
        site.save(update_fields=['par_header_title'])


def unseed_par_header_title(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_sitesettings_par_header_signatories'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='par_header_title',
            field=models.CharField(
                default='PROPERTY ACKNOWLEDGEMENT RECEIPT',
                help_text='Title line printed at the top of every PAR form (Annex A.1).',
                max_length=200,
            ),
        ),
        migrations.RunPython(seed_par_header_title, unseed_par_header_title),
    ]
