from django.db import migrations, models


def mark_supply_officer_roles(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    for role in Role.objects.all():
        should_act = (
            role.name in {'Property Custodian', 'Supply Officer'}
            or (role.can_manage_equipment and not role.can_manage_users)
        )
        if role.acts_as_supply_officer != should_act:
            role.acts_as_supply_officer = should_act
            role.save(update_fields=['acts_as_supply_officer'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_role_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='acts_as_supply_officer',
            field=models.BooleanField(
                default=False,
                help_text='Use users with this role as Supply Officer signatories for PAR/ICS forms.',
            ),
        ),
        migrations.RunPython(mark_supply_officer_roles, migrations.RunPython.noop),
    ]
