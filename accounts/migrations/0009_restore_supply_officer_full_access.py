from django.db import migrations


FULL_ACCESS = {
    'can_access_site': True,
    'can_manage_users': True,
    'can_manage_equipment': True,
    'can_view_all_equipment': True,
    'can_manage_borrowing': True,
    'can_manage_maintenance': True,
    'can_view_reports': True,
    'acts_as_supply_officer': True,
}


def restore_supply_officer_full_access(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    try:
        role = Role.objects.get(name='Supply Officer')
    except Role.DoesNotExist:
        return

    changed = False
    for field, value in FULL_ACCESS.items():
        if getattr(role, field) != value:
            setattr(role, field, value)
            changed = True

    if changed:
        role.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_supply_officer_inventory_scope'),
    ]

    operations = [
        migrations.RunPython(restore_supply_officer_full_access, migrations.RunPython.noop),
    ]
