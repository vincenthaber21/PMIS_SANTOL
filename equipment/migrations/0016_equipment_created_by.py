"""Add created_by to Equipment and backfill from audit log."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_created_by(apps, schema_editor):
    Equipment = apps.get_model('equipment', 'Equipment')
    AuditLog = apps.get_model('core', 'AuditLog')

    for equipment in Equipment.objects.filter(created_by__isnull=True):
        log = (
            AuditLog.objects.filter(
                model_name='Equipment',
                object_id=str(equipment.pk),
                action='CREATE',
            )
            .order_by('timestamp')
            .first()
        )
        if log and log.user_id:
            equipment.created_by_id = log.user_id
            equipment.save(update_fields=['created_by_id'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('equipment', '0015_equipment_property_number_pk'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipment',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                help_text='User who registered this equipment.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='equipment_created',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_created_by, migrations.RunPython.noop),
    ]
