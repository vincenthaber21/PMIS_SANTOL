from django.db import migrations


def seed_ics_signatories(apps, schema_editor):
    SiteSettings = apps.get_model('core', 'SiteSettings')
    site, _ = SiteSettings.objects.get_or_create(pk=1)
    updated = False
    defaults = {
        'ics_received_by_name': 'Rosa Lim',
        'ics_received_by_position': 'Head, Engineering',
        'ics_received_from_name': 'Maria Santos',
        'ics_received_from_position': 'Supply Officer, Administration',
    }
    for field, value in defaults.items():
        if not getattr(site, field):
            setattr(site, field, value)
            updated = True
    if updated:
        site.save()


def unseed_ics_signatories(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_sitesettings_ics_signatories'),
    ]

    operations = [
        migrations.RunPython(seed_ics_signatories, unseed_ics_signatories),
    ]
