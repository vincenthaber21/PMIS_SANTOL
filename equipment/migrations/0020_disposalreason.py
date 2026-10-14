from django.db import migrations, models
import django.db.models.deletion

DEFAULT_DISPOSAL_REASONS = [
    (1, 'Barter'),
    (2, 'Condemnation/Destruction of Properties'),
    (3, 'Direct Negotiation'),
    (4, 'Donation'),
    (5, 'Negotiated Sale'),
    (6, 'Public Auction'),
    (7, 'Return to the Supplier/Vendor'),
    (8, 'Sale to Government Officials/Employees of the Agency'),
    (9, 'Sale of Junk or Scrap and/or Recycling'),
    (10, 'Transfer of Properties to Another Government Agency'),
]


def seed_disposal_data(apps, schema_editor):
    PropertyStatus = apps.get_model('equipment', 'PropertyStatus')
    DisposalReason = apps.get_model('equipment', 'DisposalReason')

    PropertyStatus.objects.get_or_create(
        name='Dispose',
        defaults={'status': 'Active'},
    )
    for sort_order, name in DEFAULT_DISPOSAL_REASONS:
        DisposalReason.objects.get_or_create(
            name=name,
            defaults={'sort_order': sort_order, 'status': 'Active'},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0019_paymentmethod'),
    ]

    operations = [
        migrations.CreateModel(
            name='DisposalReason',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('status', models.CharField(
                    choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
                    default='Active',
                    max_length=20,
                )),
            ],
            options={
                'verbose_name': 'Disposal Reason',
                'verbose_name_plural': 'Disposal Reasons',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.AddField(
            model_name='equipment',
            name='disposal_reason',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='equipment',
                to='equipment.disposalreason',
                verbose_name='Disposal Reason',
            ),
        ),
        migrations.RunPython(seed_disposal_data, migrations.RunPython.noop),
    ]
