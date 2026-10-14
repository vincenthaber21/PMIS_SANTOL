from django.db import migrations


PERMISSION_FIELDS = (
    'can_access_site',
    'can_manage_users',
    'can_manage_equipment',
    'can_view_all_equipment',
    'can_manage_borrowing',
    'can_manage_maintenance',
    'can_view_reports',
)

FULL_ACCESS = {field: True for field in PERMISSION_FIELDS}

ROLE_DEFAULTS = {
    'Admin': {
        **FULL_ACCESS,
        'acts_as_supply_officer': False,
    },
    'Property Custodian': {
        **FULL_ACCESS,
        'acts_as_supply_officer': True,
    },
    'Supply Officer': {
        **FULL_ACCESS,
        'acts_as_supply_officer': True,
    },
}


def apply_full_access_role_defaults(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')

    for role_name, defaults in ROLE_DEFAULTS.items():
        role, _ = Role.objects.get_or_create(
            name=role_name,
            defaults={'status': 'Active'},
        )

        changed = False
        if role.status != 'Active':
            role.status = 'Active'
            changed = True

        for field, value in defaults.items():
            if getattr(role, field) != value:
                setattr(role, field, value)
                changed = True

        if changed:
            role.save()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_role_supply_officer_flag'),
    ]

    operations = [
        migrations.RunPython(apply_full_access_role_defaults, migrations.RunPython.noop),
    ]
