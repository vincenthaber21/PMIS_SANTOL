"""Backfill created_by from audit log details (property number in text)."""
import re

from django.conf import settings
from django.db import migrations


def _property_number_from_details(details):
    if not details:
        return None
    match = re.search(r'\(([0-9]{4}-[0-9]{2}-[0-9]{4}-[A-Z]{2,3}-[0-9]{4})\)', details)
    if match:
        return match.group(1)
    match = re.search(
        r'Equipment\s+([0-9]{4}-[0-9]{2}-[0-9]{4}-[A-Z]{2,3}-[0-9]{4})',
        details,
    )
    if match:
        return match.group(1)
    return None


def backfill_created_by_from_details(apps, schema_editor):
    Equipment = apps.get_model('equipment', 'Equipment')
    AuditLog = apps.get_model('core', 'AuditLog')

    for log in AuditLog.objects.filter(
        model_name='Equipment', action='CREATE', user__isnull=False,
    ).order_by('timestamp'):
        property_number = _property_number_from_details(log.details)
        if not property_number:
            continue
        try:
            equipment = Equipment.objects.get(pk=property_number)
        except Equipment.DoesNotExist:
            continue
        if equipment.created_by_id is None:
            equipment.created_by_id = log.user_id
            equipment.save(update_fields=['created_by_id'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('equipment', '0016_equipment_created_by'),
    ]

    operations = [
        migrations.RunPython(backfill_created_by_from_details, migrations.RunPython.noop),
    ]
