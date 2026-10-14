from django.db import migrations


def fix_par_custodians_to_supply_officer(apps, schema_editor):
    from core.signatories import is_supply_officer, resolve_supply_officer

    PropertyAcknowledgmentReceipt = apps.get_model('equipment', 'PropertyAcknowledgmentReceipt')
    for par in PropertyAcknowledgmentReceipt.objects.select_related('custodian__role').iterator():
        if not is_supply_officer(par.custodian):
            officer = resolve_supply_officer()
            if officer and officer.pk != par.custodian_id:
                par.custodian_id = officer.pk
                par.save(update_fields=['custodian_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_par_supply_officer_defaults'),
    ]

    operations = [
        migrations.RunPython(fix_par_custodians_to_supply_officer, migrations.RunPython.noop),
    ]
