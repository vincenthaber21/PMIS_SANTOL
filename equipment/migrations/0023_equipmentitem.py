# Generated manually for EquipmentItem catalog

from django.db import migrations, models
import django.db.models.deletion


def backfill_items_from_equipment(apps, schema_editor):
    Equipment = apps.get_model('equipment', 'Equipment')
    EquipmentItem = apps.get_model('equipment', 'EquipmentItem')
    seen = set()
    for row in (
        Equipment.objects
        .exclude(name='')
        .values_list('category_id', 'name')
        .distinct()
        .order_by('category_id', 'name')
    ):
        category_id, name = row
        if not category_id or not name:
            continue
        normalized = str(name).strip().upper()
        key = (category_id, normalized)
        if key in seen:
            continue
        seen.add(key)
        EquipmentItem.objects.get_or_create(
            category_id=category_id,
            name=normalized,
            defaults={'status': 'Active'},
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0022_reference_id_charfield'),
    ]

    operations = [
        migrations.CreateModel(
            name='EquipmentItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('status', models.CharField(choices=[('Active', 'Active'), ('Inactive', 'Inactive')], default='Active', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='equipment.category')),
            ],
            options={
                'verbose_name': 'Equipment item',
                'verbose_name_plural': 'Equipment items',
                'ordering': ['name'],
                'unique_together': {('category', 'name')},
            },
        ),
        migrations.RunPython(backfill_items_from_equipment, noop_reverse),
    ]
