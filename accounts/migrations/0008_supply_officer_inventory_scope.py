from django.db import migrations


SUPPLY_OFFICER_DEFAULTS = {
    'can_access_site': True,
    'can_manage_users': False,
    'can_manage_equipment': False,
    'can_view_all_equipment': False,
    'can_manage_borrowing': True,
    'can_manage_maintenance': False,
    'can_view_reports': True,
    'acts_as_supply_officer': True,
}


def apply_supply_officer_inventory_scope(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    try:
        role = Role.objects.get(name='Supply Officer')
    except Role.DoesNotExist:
        return

    changed = False
    for field, value in SUPPLY_OFFICER_DEFAULTS.items():
        if getattr(role, field) != value:
            setattr(role, field, value)
            changed = True

    if changed:
        role.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_full_access_role_defaults'),
    ]

    operations = [
        migrations.RunPython(apply_supply_officer_inventory_scope, migrations.RunPython.noop),
    ]
