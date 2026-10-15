from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('equipment', '0025_par_end_user_optional'),
    ]

    operations = [
        migrations.CreateModel(
            name='EquipmentRepair',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('repair_date', models.DateField()),
                ('nature', models.CharField(choices=[('Minor', 'Minor'), ('Major', 'Major')], max_length=10)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('equipment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='repairs', to='equipment.equipment')),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_equipment_repairs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-repair_date', '-created_at'],
            },
        ),
    ]
