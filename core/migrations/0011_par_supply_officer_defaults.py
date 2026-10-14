from django.db import migrations, models


def seed_par_supply_officer_defaults(apps, schema_editor):
    SiteSettings = apps.get_model('core', 'SiteSettings')
    site, _ = SiteSettings.objects.get_or_create(pk=1)
    updated = False
    defaults = {
        'par_received_from_position': 'Supply Officer',
    }
    for field, value in defaults.items():
        if not (getattr(site, field) or '').strip():
            setattr(site, field, value)
            updated = True
    if not (site.par_received_from_name or '').strip():
        from accounts.models import User
        officer = (
            User.objects.filter(
                role__can_manage_equipment=True,
                role__can_manage_users=False,
                is_active=True,
            ).first()
            or User.objects.filter(role__can_manage_equipment=True, is_active=True).first()
        )
        if officer:
            site.par_received_from_name = officer.get_full_name() or officer.username
            updated = True
    if updated:
        site.save()


def fix_par_supply_officer_custodians(apps, schema_editor):
    from core.signatories import is_supply_officer, resolve_supply_officer

    PropertyAcknowledgmentReceipt = apps.get_model('equipment', 'PropertyAcknowledgmentReceipt')
    for par in PropertyAcknowledgmentReceipt.objects.select_related('custodian__role').iterator():
        if not is_supply_officer(par.custodian):
            officer = resolve_supply_officer()
            if officer and officer.pk != par.custodian_id:
                par.custodian_id = officer.pk
                par.save(update_fields=['custodian_id'])


def unseed_par_supply_officer_defaults(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_sitesettings_par_use_site_signatories'),
        ('equipment', '0015_equipment_property_number_pk'),
        ('accounts', '0005_role_permissions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesettings',
            name='par_received_from_position',
            field=models.CharField(
                blank=True,
                default='Supply Officer',
                help_text='Position/office on PAR “Received from” signature block (e.g. Supply Officer).',
                max_length=200,
            ),
        ),
        migrations.RunPython(seed_par_supply_officer_defaults, unseed_par_supply_officer_defaults),
        migrations.RunPython(fix_par_supply_officer_custodians, unseed_par_supply_officer_defaults),
    ]
