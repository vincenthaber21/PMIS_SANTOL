from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('equipment', '0024_equipment_registration_batch'),
    ]

    operations = [
        migrations.AlterField(
            model_name='propertyacknowledgmentreceipt',
            name='end_user',
            field=models.ForeignKey(
                blank=True,
                help_text='Accountable end-user. Blank until the item is assigned.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='par_receipts',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
