from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0013_ics_custodian_slip_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipment',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='equipment',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('cash', 'Cash'),
                    ('check', 'Check'),
                    ('bank_transfer', 'Bank Transfer'),
                    ('credit', 'Credit'),
                    ('other', 'Other'),
                ],
                default='',
                max_length=30,
                verbose_name='Payment Method',
            ),
        ),
    ]
