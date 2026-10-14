from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0023_equipmentitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipment',
            name='registration_batch',
            field=models.UUIDField(
                blank=True,
                db_index=True,
                help_text='Shared id for equipment registered together in one save (multi-quantity).',
                null=True,
            ),
        ),
    ]
