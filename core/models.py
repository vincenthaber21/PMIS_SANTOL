"""Core app models: AuditLog, Notification, SiteSettings, and DatabaseDownload."""
from django.db import models
from django.conf import settings
from django.core.validators import FileExtensionValidator


class SiteSettings(models.Model):
    """Singleton site branding — name and logo editable in Django admin."""

    site_short_name = models.CharField(
        max_length=50,
        default='PMS',
        help_text='Short name shown in the sidebar and page titles (e.g. PMS).',
    )
    site_full_name = models.CharField(
        max_length=200,
        default='Property Management System',
        help_text='Full system name shown under the short name.',
    )
    tagline = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Optional tagline on the login page.',
    )
    logo = models.ImageField(
        upload_to='site/',
        blank=True,
        help_text='Upload a square logo image. Leave empty to use the letter below.',
    )
    logo_letter = models.CharField(
        max_length=2,
        default='P',
        help_text='Letter shown in the logo box when no image is uploaded.',
    )
    property_number_lgu_code = models.CharField(
        max_length=40,
        default='1042',
        verbose_name='Property number LGU code',
        help_text=(
            'Code printed on inventory tags, and used as the property-number prefix when '
            'legacy mode is enabled. Use a numeric code (0621) or a custom prefix (LGU-SANTOL).'
        ),
    )
    property_number_use_legacy_lgu_code = models.BooleanField(
        default=False,
        verbose_name='Use legacy numeric LGU code for property numbers',
        help_text=(
            'When enabled, auto-generated property numbers start with the LGU code above '
            '(e.g. LGU-SANTOL-201-2027-PR-0001 or 0621-201-2027-PR-0001). When disabled, '
            'they use the normal form number (e.g. PAR-201-2027-PR-0001).'
        ),
    )
    lgu_municipality = models.CharField(
        max_length=100,
        default='SUDIPEN',
        help_text='Municipality name printed on PAR/ICS headers (e.g. SUDIPEN).',
    )
    lgu_province = models.CharField(
        max_length=100,
        default='LA UNION',
        help_text='Province name printed on PAR headers (e.g. LA UNION → PROVINCE OF LA UNION).',
    )
    par_header_title = models.CharField(
        max_length=200,
        default='PROPERTY ACKNOWLEDGEMENT RECEIPT',
        help_text='Title line printed at the top of every PAR form (Annex A.1).',
    )
    par_use_site_signatories = models.BooleanField(
        default=False,
        verbose_name='Use site default signatories',
        help_text=(
            'When enabled, print the names and positions below on every PAR. '
            'When disabled, use each PAR’s assigned end-user and supply officer instead.'
        ),
    )
    par_received_by_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Printed name on PAR “Received by” signature block. Leave blank to use the end-user on each PAR.',
    )
    par_received_by_position = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Position/office on PAR “Received by” signature block (e.g. Operations).',
    )
    par_received_from_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Printed name on PAR “Received from” signature block. Leave blank to use the custodian on each PAR.',
    )
    par_received_from_position = models.CharField(
        max_length=200,
        blank=True,
        default='Supply Officer',
        help_text='Position/office on PAR “Received from” signature block (e.g. Supply Officer).',
    )
    ics_received_by_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Printed name on ICS “Received by” signature block.',
    )
    ics_received_by_position = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Position/office on ICS “Received by” signature block (e.g. Head, Engineering).',
    )
    ics_received_from_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Printed name on ICS “Received from” signature block.',
    )
    ics_received_from_position = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Position/office on ICS “Received from” signature block (e.g. Supply Officer, Administration).',
    )
    ics_supplier_address = models.CharField(
        max_length=300,
        blank=True,
        default='',
        help_text='Default supplier address printed on every ICS header (Appendix 59).',
    )
    ics_po_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='P.O. number',
        help_text='Default purchase order number printed on every ICS header.',
    )
    ics_header_date = models.DateField(
        null=True,
        blank=True,
        help_text='Default date shown in the ICS header supplier block. Leave blank to use each slip’s issue date.',
    )
    ics_mode_of_procurement = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='MOP',
        help_text='Default mode of procurement (MOP) printed on every ICS header.',
    )
    inventory_tag_date_counted = models.DateField(
        null=True,
        blank=True,
        help_text=(
            'Default Date:(Counted) shown on printed inventory tags. '
            'Users can change this value before printing.'
        ),
    )
    inventory_tag_coa_representative = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text=(
            'Default COA Representative shown on printed inventory tags. '
            'Users can change this value before printing.'
        ),
    )

    class Meta:
        verbose_name = 'Site settings'
        verbose_name_plural = 'Site settings'

    def __str__(self):
        return f'{self.site_short_name} — {self.site_full_name}'

    def save(self, *args, **kwargs):
        self.pk = 1
        previous = SiteSettings.objects.filter(pk=1).values(
            'logo',
            'property_number_lgu_code',
            'property_number_use_legacy_lgu_code',
        ).first()
        old_logo = (previous or {}).get('logo') or ''
        super().save(*args, **kwargs)
        from .admin_branding import invalidate_admin_branding_cache
        from .logo_image import clear_login_logo_cache

        invalidate_admin_branding_cache()
        if old_logo:
            clear_login_logo_cache(old_logo)
        if self.logo:
            clear_login_logo_cache(self.logo.name)

        number_changed = previous is None or (
            (previous.get('property_number_lgu_code') or '').strip()
            != (self.property_number_lgu_code or '').strip()
            or bool(previous.get('property_number_use_legacy_lgu_code'))
            != bool(self.property_number_use_legacy_lgu_code)
        )
        if number_changed:
            from equipment.property_number import sync_equipment_property_numbers
            sync_equipment_property_numbers()

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @staticmethod
    def format_lgu_municipality_prefix(municipality):
        """Build LGU-{Municipality}, keeping the name as entered aside from a capital first letter."""
        name = (municipality or '').strip()
        if not name:
            return 'LGU'
        words = [word[:1].upper() + word[1:] for word in name.split() if word]
        return f'LGU-{" ".join(words)}' if words else 'LGU'

    @property
    def property_number_lgu_label(self):
        return self.format_lgu_municipality_prefix(self.lgu_municipality)

    @property
    def property_number_prefix_segment(self):
        """LGU prefix used only when legacy mode is enabled. Empty in normal mode."""
        if self.property_number_use_legacy_lgu_code:
            return (self.property_number_lgu_code or '').strip()
        return ''


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('ARCHIVE', 'Archive'),
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('RETURN', 'Return'),
        ('DEACTIVATE', 'Deactivate'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.timestamp} | {self.user} | {self.action} | {self.model_name}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ('borrow', 'Borrow'),
        ('maintenance', 'Maintenance'),
        ('warranty', 'Warranty'),
        ('overdue', 'Overdue'),
        ('info', 'Info'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    message = models.TextField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='info')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user}: {self.message[:50]}"


class DatabaseDownload(models.Model):
    """Record of a full database export saved for history / re-download."""

    FORMAT_CHOICES = [
        ('json', 'JSON'),
        ('zip', 'ZIP'),
    ]
    QUARTER_CHOICES = [
        (1, 'Q1 (Jan–Mar)'),
        (2, 'Q2 (Apr–Jun)'),
        (3, 'Q3 (Jul–Sep)'),
        (4, 'Q4 (Oct–Dec)'),
    ]

    filename = models.CharField(max_length=255)
    export_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    file = models.FileField(
        upload_to='database_backups/%Y/%m/',
        validators=[FileExtensionValidator(['json', 'zip'])],
    )
    file_size = models.PositiveBigIntegerField(default=0, help_text='Size in bytes')
    object_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of serialized objects in the dump',
    )
    year = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Calendar year for quarterly backups',
    )
    quarter = models.PositiveSmallIntegerField(
        choices=QUARTER_CHOICES,
        null=True,
        blank=True,
        help_text='Quarter (1–4) this backup belongs to',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='database_downloads',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Database download'
        verbose_name_plural = 'Database downloads'

    def __str__(self):
        label = self.quarter_label
        if label:
            return f'{label} — {self.filename}'
        return f'{self.filename} ({self.created_at:%Y-%m-%d %H:%M})'

    @property
    def quarter_label(self):
        if self.year and self.quarter:
            return f'Q{self.quarter} {self.year}'
        return ''

    @property
    def file_size_display(self):
        n = self.file_size or 0
        if n < 1024:
            return f'{n} B'
        if n < 1024 * 1024:
            return f'{n / 1024:.1f} KB'
        return f'{n / (1024 * 1024):.2f} MB'


class QuarterlyDatabaseBackup(models.Model):
    """
    Choose a year + quarter, then automatically download a full database dump
    tagged for that quarter.
    """

    QUARTER_CHOICES = DatabaseDownload.QUARTER_CHOICES

    year = models.PositiveIntegerField(
        help_text='Calendar year (e.g. 2026)',
    )
    quarter = models.PositiveSmallIntegerField(
        choices=QUARTER_CHOICES,
        help_text='Which quarter this full-data backup is for',
    )
    download = models.OneToOneField(
        DatabaseDownload,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quarterly_backup',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quarterly_backups',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-year', '-quarter', '-created_at']
        verbose_name = 'Quarterly database backup'
        verbose_name_plural = 'Quarterly database backups'
        indexes = [
            models.Index(fields=['-year', '-quarter']),
        ]

    def __str__(self):
        return f'Q{self.quarter} {self.year}'

    @property
    def label(self):
        return f'Q{self.quarter} {self.year}'

    @property
    def quarter_display(self):
        return dict(self.QUARTER_CHOICES).get(self.quarter, f'Q{self.quarter}')

    @classmethod
    def current_year(cls):
        from django.utils import timezone
        return timezone.localdate().year

    @classmethod
    def current_quarter(cls):
        from django.utils import timezone
        month = timezone.localdate().month
        return ((month - 1) // 3) + 1


class AutoDatabaseDownloadSchedule(models.Model):
    """
    Singleton countdown: set N days starting today; when the counter
    reaches 0, automatically create a full database ZIP backup.
    """

    is_enabled = models.BooleanField(
        default=True,
        help_text='When enabled, PMS creates a ZIP backup when the day counter reaches 0.',
    )
    countdown_days = models.PositiveIntegerField(
        default=100,
        help_text='How many days from the start date until automatic download (e.g. 100).',
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text='Date the countdown started (usually today when you save).',
    )
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_download = models.ForeignKey(
        DatabaseDownload,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Automatic database download schedule'
        verbose_name_plural = 'Automatic database download schedule'

    def __str__(self):
        status = 'ON' if self.is_enabled else 'OFF'
        return f'{status} — {self.schedule_display}'

    def save(self, *args, **kwargs):
        from django.utils import timezone

        self.pk = 1
        self.countdown_days = max(1, min(3650, int(self.countdown_days or 1)))
        if self.start_date is None:
            self.start_date = timezone.localdate()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        from django.utils import timezone

        obj, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'countdown_days': 100,
                'start_date': timezone.localdate(),
                'is_enabled': True,
            },
        )
        if not created and obj.start_date is None:
            obj.start_date = timezone.localdate()
            obj.save(update_fields=['start_date', 'updated_at'])
        return obj

    @property
    def target_date(self):
        """Date when countdown reaches 0 (start + N days)."""
        from datetime import timedelta

        if not self.start_date:
            return None
        return self.start_date + timedelta(days=self.countdown_days)

    @property
    def days_remaining(self):
        """Days left until automatic download (0 = due today)."""
        from django.utils import timezone

        target = self.target_date
        if not target:
            return None
        remaining = (target - timezone.localdate()).days
        return max(0, remaining)

    @property
    def days_elapsed(self):
        from django.utils import timezone

        if not self.start_date:
            return 0
        elapsed = (timezone.localdate() - self.start_date).days
        return max(0, min(self.countdown_days, elapsed))

    @property
    def schedule_display(self):
        remaining = self.days_remaining
        if remaining is None:
            return f'{self.countdown_days} days (not started)'
        if remaining == 0:
            return f'{self.countdown_days}-day countdown — due now (0 days left)'
        return (
            f'{self.countdown_days}-day countdown — '
            f'{remaining} day{"s" if remaining != 1 else ""} left'
        )

    def next_run_datetime(self):
        """End of target date in local timezone (Asia/Manila)."""
        from datetime import datetime

        from django.utils import timezone

        target = self.target_date
        if not target:
            return None
        tz = timezone.get_current_timezone()
        naive = datetime(target.year, target.month, target.day, 0, 0)
        return timezone.make_aware(naive, tz)

    def is_due(self, window_minutes=None):
        """True if enabled and countdown has reached 0 (today >= target)."""
        from django.utils import timezone

        if not self.is_enabled:
            return False
        target = self.target_date
        if not target:
            return False
        today = timezone.localdate()
        if today < target:
            return False

        if self.last_run_at:
            last = timezone.localtime(self.last_run_at).date()
            # Already ran for this countdown cycle.
            if last >= target:
                return False
        return True

    def mark_run(self, download=None, restart=True):
        """
        Record that the automatic backup ran.
        By default restarts the same N-day countdown from today.
        """
        from django.utils import timezone

        self.last_run_at = timezone.now()
        if download is not None:
            self.last_download = download
        if restart:
            self.start_date = timezone.localdate()
        self.save(
            update_fields=[
                'last_run_at',
                'last_download',
                'start_date',
                'updated_at',
            ]
        )

    def restart_countdown(self, days=None):
        """Reset countdown starting today."""
        from django.utils import timezone

        if days is not None:
            self.countdown_days = days
        self.start_date = timezone.localdate()
        self.save(update_fields=['countdown_days', 'start_date', 'updated_at'])
