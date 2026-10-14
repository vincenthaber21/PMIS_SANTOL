from django.db import migrations


def rename_dispose_to_disposed(apps, schema_editor):
    PropertyStatus = apps.get_model('equipment', 'PropertyStatus')
    PropertyStatus.objects.filter(name='Dispose').update(name='Disposed')
    PropertyStatus.objects.get_or_create(
        name='Disposed',
        defaults={'status': 'Active'},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0020_disposalreason'),
    ]

    operations = [
        migrations.RunPython(rename_dispose_to_disposed, migrations.RunPython.noop),
    ]
