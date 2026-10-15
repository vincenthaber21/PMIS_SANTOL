from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_property_number_unique_per_unit'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='ppe_depreciable_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('95.00'),
                help_text=(
                    'Percent of acquisition cost that is depreciated on the PPE ledger card '
                    '(Appendix 70). 95 leaves a 5% residual value. '
                    'A purchase on days 1–15 starts depreciation in that month; '
                    'day 16 or later starts on the first day of the next month.'
                ),
                max_digits=5,
                validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
                verbose_name='Depreciable value (%)',
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='ppe_prepared_by_name',
            field=models.CharField(
                blank=True,
                default='HANS CHRISTOPHER S. TAHADLANGIT',
                help_text='Name printed on the PPE ledger card “Prepared by” line.',
                max_length=200,
                verbose_name='Prepared by',
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='ppe_prepared_by_position',
            field=models.CharField(
                blank=True,
                default='Accounting Clerk I',
                help_text='Position printed under the PPE ledger card preparer.',
                max_length=200,
                verbose_name='Prepared by position',
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='ppe_noted_by_name',
            field=models.CharField(
                blank=True,
                default='JOANALYN A. MAON, CPA',
                help_text='Name printed on the PPE ledger card “Noted by” line.',
                max_length=200,
                verbose_name='Noted by',
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='ppe_noted_by_position',
            field=models.CharField(
                blank=True,
                default='Municipal Accountant',
                help_text='Position printed under the PPE ledger card noting officer.',
                max_length=200,
                verbose_name='Noted by position',
            ),
        ),
    ]
