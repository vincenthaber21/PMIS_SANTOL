"""Reports app models."""
from django.conf import settings
from django.db import models


class ParExportSignatory(models.Model):
    """
    Signature block captured when generating a PAR PDF from Reports.

    Maps to the PAR form fields:
    - Received by → signature_over_printed_name, position_office
    - Received from → supply_officer (+ position)
    """

    signature_over_printed_name = models.CharField(
        max_length=200,
        verbose_name='Signature Over Printed Name',
        help_text='Printed on PAR “Received by” block.',
    )
    position_office = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Position/Office',
        help_text='Office or title on PAR “Received by” block.',
    )
    supply_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='par_export_signatures_as_supply_officer',
        help_text='User shown on PAR “Received from” block.',
    )
    supply_officer_position = models.CharField(
        max_length=200,
        blank=True,
        default='Supply Officer',
        help_text='Position/office for the supply officer signature block.',
    )
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='par_exports_signed',
    )
    exported_at = models.DateTimeField(auto_now_add=True)
    report_type = models.CharField(max_length=50, blank=True)
    item_count = models.PositiveIntegerField(default=0)
    filter_department_id = models.CharField(max_length=20, blank=True)
    filter_personnel_id = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['-exported_at']
        verbose_name = 'PAR export signatory'
        verbose_name_plural = 'PAR export signatories'

    def __str__(self):
        return (
            f'{self.signature_over_printed_name} — '
            f'{self.exported_at:%Y-%m-%d %H:%M}'
        )
