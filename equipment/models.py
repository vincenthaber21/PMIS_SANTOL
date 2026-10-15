"""Equipment app models: Department and Equipment."""
import os
import re
import datetime
import hashlib
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone


class Department(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    @property
    def display_label(self):
        return f'{self.code} — {self.name}'

    class Meta:
        ordering = ['code']
        verbose_name = 'Office / Department'
        verbose_name_plural = 'Offices / Departments'


def user_display_name(user):
    """Return a stable display name for assignment history."""
    if not user:
        return 'Unassigned'
    return user.get_full_name() or user.username


def normalize_equipment_name(name):
    """Uppercase article/item name for consistent professional display."""
    if not name:
        return ''
    return str(name).strip().upper()


class Category(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(
        max_length=20, unique=True,
        help_text='Category code, e.g. 05-01',
    )
    property_type_code = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Optional label on PAR/ICS. The property number uses the category code instead.',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    @property
    def display_label(self):
        return f'{self.code} — {self.name}'

    class Meta:
        ordering = ['code']
        verbose_name_plural = 'categories'


class EquipmentItem(models.Model):
    """Article/item name catalog scoped to an equipment category."""
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name='items',
    )
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('category', 'name')]
        verbose_name = 'Equipment item'
        verbose_name_plural = 'Equipment items'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = normalize_equipment_name(self.name)
        super().save(*args, **kwargs)


class PropertyStatus(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    DEFAULT_NEW_EQUIPMENT = 'Working'
    DISPOSE_STATUS = 'Disposed'
    INVENTORY_TAG_BLOCKED_STATUSES = frozenset({'disposed', 'unserviceable'})

    @classmethod
    def is_dispose(cls, status):
        return bool(status and status.name.lower() == cls.DISPOSE_STATUS.lower())

    @classmethod
    def blocks_inventory_tag(cls, status):
        """True when inventory tag printing must be blocked for security."""
        if not status:
            return False
        return status.name.strip().lower() in cls.INVENTORY_TAG_BLOCKED_STATUSES

    @classmethod
    def default_for_new_equipment(cls):
        """Property status assigned automatically when registering equipment."""
        obj, _ = cls.objects.get_or_create(
            name=cls.DEFAULT_NEW_EQUIPMENT,
            defaults={'status': cls.STATUS_ACTIVE},
        )
        return obj

    class Meta:
        ordering = ['name']
        verbose_name = 'Property Status'
        verbose_name_plural = 'Property Statuses'


class Supplier(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=200, unique=True)
    address = models.CharField(max_length=300, blank=True, default='')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'


class FundSource(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(
        max_length=20, unique=True,
        help_text='Fund cluster code, e.g. 01',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    @property
    def display_label(self):
        return f'{self.code} — {self.name}'

    class Meta:
        ordering = ['code']
        verbose_name = 'Fund Source'
        verbose_name_plural = 'Fund Sources'


class ModeOfProcurement(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = 'Mode of Procurement'
        verbose_name_plural = 'Modes of Procurement'


class PaymentMethod(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = 'Payment Method'
        verbose_name_plural = 'Payment Methods'


class DisposalReason(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    name = models.CharField(max_length=200, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Disposal Reason'
        verbose_name_plural = 'Disposal Reasons'


class ChartOfAccount(models.Model):
    """Annex B reference data — semi-expendable account codes (not a browsable module)."""
    ACCOUNT_TYPES = [
        ('asset', 'Semi-Expendable Asset'),
        ('expense_issuance', 'Expense on Issuance'),
    ]
    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default='asset')
    categories = models.ManyToManyField(Category, blank=True, related_name='chart_accounts')

    def __str__(self):
        return f'{self.code} — {self.description}'

    class Meta:
        ordering = ['code']
        verbose_name = 'Chart of Account'
        verbose_name_plural = 'Chart of Accounts'


class AccountingEntry(models.Model):
    """Auto-generated JEV entries (Annex C) — side effects of acquisition/issuance/reclassification."""
    ENTRY_TYPES = [
        ('ACQUISITION', 'Acquisition'),
        ('ISSUANCE', 'Issuance'),
        ('RECLASSIFICATION', 'Reclassification'),
    ]
    equipment = models.ForeignKey(
        'Equipment', on_delete=models.CASCADE, related_name='accounting_entries'
    )
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    jev_number = models.CharField(max_length=30, unique=True)
    debit_account = models.CharField(max_length=20)
    credit_account = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    fund = models.CharField(max_length=50, default='General Fund')
    particulars = models.TextField()
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=50, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='accounting_entries'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.jev_number} — {self.get_entry_type_display()}'

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'accounting entries'


class Equipment(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Borrowed', 'Borrowed'),
        ('Maintenance', 'Maintenance'),
        ('Retired', 'Retired'),
    ]
    DEPRECIATION_CHOICES = [
        ('straight_line', 'Straight Line'),
        ('declining_balance', 'Declining Balance'),
    ]
    # Identification
    property_number = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='equipment'
    )
    asset_classification = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True, default='')

    # Acquisition
    purchase_date = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    acquisition_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='COA acquisition cost for classification (₱)',
    )
    fund = models.CharField(max_length=50, default='General Fund')
    fund_source = models.ForeignKey(
        FundSource, on_delete=models.PROTECT, null=True, blank=True,
        related_name='equipment',
    )
    estimated_useful_life = models.PositiveIntegerField(
        default=5, help_text='COA estimated useful life in years',
    )
    criterion_future_benefits = models.BooleanField(
        default=True, verbose_name='Probable future economic benefits',
    )
    criterion_measurable_cost = models.BooleanField(
        default=True, verbose_name='Cost can be measured reliably',
    )
    criterion_useful_life = models.BooleanField(
        default=True, verbose_name='Useful life exceeds one year',
    )
    criterion_not_for_resale = models.BooleanField(
        default=True, verbose_name='Not intended for sale in ordinary course',
    )
    classification = models.CharField(
        max_length=30, blank=True, editable=False,
        help_text='Auto-computed COA classification',
    )
    coa_account_code = models.CharField(
        max_length=20, blank=True, editable=False,
        help_text='Auto-mapped Annex B account code',
    )
    depreciation_method = models.CharField(
        max_length=20, choices=DEPRECIATION_CHOICES, default='straight_line'
    )
    warranty_until = models.DateField(null=True, blank=True)
    supplier = models.ForeignKey(
        'Supplier', on_delete=models.PROTECT, null=True, blank=True,
        related_name='equipment',
    )
    mode_of_procurement = models.ForeignKey(
        ModeOfProcurement, on_delete=models.PROTECT, null=True, blank=True,
        related_name='equipment',
    )
    purchase_order_no = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='P.O. Number',
        help_text='Purchase order number for ICS / procurement records',
    )
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, null=True, blank=True,
        related_name='equipment',
        verbose_name='Payment Method',
    )
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default='unit')

    # Location & Assignment
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name='equipment'
    )
    current_location = models.CharField(max_length=200, blank=True)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assigned_equipment'
    )

    # Status & Condition
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    property_status = models.ForeignKey(
        PropertyStatus, on_delete=models.PROTECT, null=True, blank=True,
        related_name='equipment',
    )
    disposal_reason = models.ForeignKey(
        DisposalReason, on_delete=models.PROTECT, null=True, blank=True,
        related_name='equipment',
        verbose_name='Disposal Reason',
    )
    expected_lifespan_years = models.PositiveIntegerField(default=5)
    condition_score = models.IntegerField(default=100, help_text='0–100')
    utilization_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Maintenance
    maintenance_schedule = models.CharField(max_length=100, blank=True, help_text='e.g. Every 6 months')
    last_inspection_date = models.DateField(null=True, blank=True)

    # QR Code
    qr_code = models.ImageField(upload_to='qr_codes/', null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='equipment_created',
        help_text='User who registered this equipment.',
    )
    registration_batch = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Shared id for equipment registered together in one save (multi-quantity).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['property_number']

    def __str__(self):
        return f"{self.property_number} – {self.display_name}"

    @property
    def display_name(self):
        """Professional display name — always uppercase."""
        return normalize_equipment_name(self.name)

    def classify(self):
        """COA Circular 3.1 classification (read-only property)."""
        from .coa import classify_equipment
        return classify_equipment(self)

    @property
    def form_type(self):
        """COA issuance form: PAR for PPE, ICS for semi-expendable / low-value."""
        from .coa import CLASSIFICATION_PPE
        return 'PAR' if self.classification == CLASSIFICATION_PPE else 'ICS'

    @property
    def display_location(self):
        """Preferred human-readable location for UI display."""
        if self.current_location:
            return self.current_location
        if self.department_id:
            return self.department.name
        return '—'

    @property
    def allows_inventory_tag(self):
        """Whether an inventory tag may be printed for this equipment."""
        return not PropertyStatus.blocks_inventory_tag(self.property_status)

    @property
    def display_purchase_order_no(self):
        """Preferred purchase order number, with legacy ICS fallback when needed."""
        if self.purchase_order_no:
            return self.purchase_order_no
        latest_ics_item = (
            self.ics_items.select_related('ics')
            .order_by('-ics__date', '-ics_id', '-pk')
            .first()
        )
        if latest_ics_item and latest_ics_item.ics.po_number:
            return latest_ics_item.ics.po_number
        return '—'

    def save(self, *args, **kwargs):
        if self.name is not None:
            self.name = normalize_equipment_name(self.name)

        # Sync COA cost / useful life with legacy fields
        if not self.acquisition_cost and self.purchase_cost:
            self.acquisition_cost = self.purchase_cost
        elif self.acquisition_cost and not self.purchase_cost:
            self.purchase_cost = self.acquisition_cost
        if self.estimated_useful_life:
            self.expected_lifespan_years = self.estimated_useful_life
        elif self.expected_lifespan_years and not self.estimated_useful_life:
            self.estimated_useful_life = self.expected_lifespan_years

        if self.fund_source_id:
            self.fund = self.fund_source.name
        if self.department_id and not self.current_location:
            self.current_location = self.department.name

        from .coa import update_coa_fields
        old_classification = None
        if self.pk:
            try:
                old_classification = Equipment.objects.values_list(
                    'classification', flat=True
                ).get(pk=self.pk)
            except Equipment.DoesNotExist:
                pass

        update_coa_fields(self)
        self._coa_old_classification = old_classification
        self._coa_is_new = not self.pk

        super().save(*args, **kwargs)
        if self.property_number:
            self.ensure_qr_code_current()

    def get_qr_label_fields(self):
        """Key identification fields shown on the QR label and encoded in the QR."""
        def display_value(value, default='N/A'):
            if value is None:
                return default
            if isinstance(value, str):
                cleaned = value.strip()
                return cleaned or default
            return value

        if self.fund_source_id:
            fund = str(self.fund_source)
        elif self.fund:
            fund = self.fund
        else:
            fund = 'N/A'

        if self.assigned_user_id:
            assigned = (
                self.assigned_user.get_full_name() or self.assigned_user.username
            )
        else:
            assigned = 'N/A'

        acquisition = 'N/A'
        if self.acquisition_cost:
            acquisition = f'₱{self.acquisition_cost:,.2f}'

        fields = [
            ('Name', display_value(self.display_name)),
            ('Property No.', display_value(self.property_number)),
            ('Category', display_value(self.category.name if self.category_id else None)),
            ('Classification', display_value(self.classification)),
            ('Assigned To', display_value(assigned)),
            ('Property Status', display_value(str(self.property_status) if self.property_status_id else None)),
        ]
        if PropertyStatus.is_dispose(self.property_status):
            fields.append((
                'Disposal Reason',
                display_value(str(self.disposal_reason) if self.disposal_reason_id else None),
            ))
        fields.extend([
            ('Status', display_value(self.status)),
            ('Supplier', display_value(str(self.supplier) if self.supplier_id else None)),
            ('Procurement', display_value(str(self.mode_of_procurement) if self.mode_of_procurement_id else None)),
            ('Fund Source', display_value(fund)),
            ('Purchase Date', self.purchase_date.strftime('%Y-%m-%d') if self.purchase_date else 'N/A'),
            ('Acquisition Cost', acquisition),
        ])
        return fields

    def get_qr_payload(self):
        """Text encoded in the QR image so scanners show equipment details directly."""
        lines = [
            'PROPERTY MANAGEMENT SYSTEM',
            '',
            '--- Equipment Identification ---',
            '',
        ]
        for label, value in self.get_qr_label_fields():
            lines.append(f'{label}: {value}')
        return '\n'.join(lines)

    @classmethod
    def find_by_scanned_code(cls, code):
        """Resolve equipment from a scanned QR payload or legacy property number."""
        import re

        code = (code or '').strip()
        if not code:
            return None

        equipment = cls.objects.filter(property_number__iexact=code).first()
        if equipment:
            return equipment

        pk_match = re.search(r'/equipment/([^/]+)/?', code)
        if pk_match:
            return cls.objects.filter(pk=pk_match.group(1)).first()

        for pattern in (
            r'Property No\.?:\s*(.+)',
        ):
            match = re.search(pattern, code, re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip().split('\n')[0].strip()
                equipment = cls.objects.filter(property_number__iexact=value).first()
                if equipment:
                    return equipment
        return None

    QR_PAYLOAD_RELATED = (
        'category', 'assigned_user', 'property_status', 'disposal_reason',
        'supplier', 'mode_of_procurement', 'fund_source',
    )

    def _fetch_for_qr(self):
        """Load equipment with related fields needed for an accurate QR payload."""
        if not self.pk:
            return self
        try:
            return Equipment.objects.select_related(*self.QR_PAYLOAD_RELATED).get(pk=self.pk)
        except Equipment.DoesNotExist:
            return self

    def get_qr_payload_hash(self):
        """Short hash of the current QR payload text."""
        payload = self.get_qr_payload()
        return hashlib.md5(payload.encode('utf-8')).hexdigest()[:12]

    def stored_qr_payload_hash(self):
        """Hash embedded in the stored QR filename, if present."""
        if not self.qr_code or not self.qr_code.name:
            return None
        match = re.search(r'_([a-f0-9]{12})\.png$', self.qr_code.name)
        return match.group(1) if match else None

    def qr_code_is_current(self):
        """True when the stored QR image matches the current equipment details."""
        stored_hash = self.stored_qr_payload_hash()
        if not stored_hash:
            return False
        return stored_hash == self.get_qr_payload_hash()

    def ensure_qr_code_current(self):
        """Regenerate the stored QR image when equipment details have changed."""
        if not self.property_number:
            return False
        source = self._fetch_for_qr()
        if source.qr_code_is_current():
            return False
        source._generate_qr_code()
        if source is not self:
            self.qr_code = source.qr_code
        return True

    def _generate_qr_code(self, request=None):
        """Generate a QR code image that displays equipment details when scanned."""
        source = self._fetch_for_qr() if self.pk else self
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_L
            from io import BytesIO
            from django.core.files.base import ContentFile

            # ERROR_CORRECT_L keeps the module count low so the many detail lines
            # stay scannable even when the QR is printed at a small size.
            qr = qrcode.QRCode(
                version=None,
                error_correction=ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            payload = source.get_qr_payload()
            qr.add_data(payload)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            payload_hash = hashlib.md5(payload.encode('utf-8')).hexdigest()[:12]
            filename = f'qr_{source.property_number}_{payload_hash}.png'
            if source.qr_code and source.qr_code.name:
                try:
                    source.qr_code.storage.delete(source.qr_code.name)
                except Exception:
                    pass
            source.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)
            Equipment.objects.filter(pk=source.pk).update(qr_code=source.qr_code.name)
            if source is not self and self.pk == source.pk:
                self.qr_code = source.qr_code
        except Exception:
            pass

    @property
    def coa_cost(self):
        """Effective cost for COA purposes."""
        from .coa import effective_cost
        return effective_cost(self)

    @property
    def current_book_value(self):
        """Compute book value using selected depreciation method."""
        cost_val = self.acquisition_cost or self.purchase_cost
        if not self.purchase_date or cost_val <= 0:
            return cost_val

        today = timezone.now().date()
        age_years = (today - self.purchase_date).days / 365.25
        lifespan = self.estimated_useful_life or self.expected_lifespan_years or 5
        cost = Decimal(str(cost_val))

        if self.depreciation_method == 'straight_line':
            annual_dep = cost / lifespan
            value = cost - (Decimal(str(min(age_years, lifespan))) * annual_dep)
        else:  # declining_balance
            rate = Decimal('2') / Decimal(str(lifespan))
            value = cost * ((1 - rate) ** Decimal(str(min(age_years, lifespan))))

        return max(value, Decimal('0'))

    @property
    def is_warranty_valid(self):
        if not self.warranty_until:
            return False
        return self.warranty_until >= timezone.now().date()

    @property
    def age_years(self):
        if not self.purchase_date:
            return 0
        return round((timezone.now().date() - self.purchase_date).days / 365.25, 1)

    @property
    def risk_score(self):
        """Derive risk score from condition, age, and repair frequency."""
        from maintenance.models import MaintenanceRequest
        repair_count = MaintenanceRequest.objects.filter(equipment=self).count()
        lifespan = self.expected_lifespan_years or 5
        age_ratio = min(self.age_years / lifespan, 1.0)
        condition_penalty = (100 - self.condition_score) / 100
        repair_penalty = min(repair_count * 0.05, 0.3)
        score = (age_ratio * 0.4 + condition_penalty * 0.4 + repair_penalty * 0.2) * 100
        return round(score, 1)

    @property
    def expected_remaining_life(self):
        """Estimated remaining useful life in years."""
        remaining = self.expected_lifespan_years - self.age_years
        return max(round(remaining, 1), 0)

    def hard_delete(self, *, deleted_by=None):
        """Permanently remove this equipment and dependent records that block deletion."""
        from django.db import transaction
        from core.models import AuditLog

        pk = self.pk
        name = self.name
        par_ids = list(self.par_items.values_list('par_id', flat=True))
        ics_ids = list(self.ics_items.values_list('ics_id', flat=True))

        with transaction.atomic():
            self.par_items.all().delete()
            self.ics_items.all().delete()

            for par_id in par_ids:
                par = PropertyAcknowledgmentReceipt.objects.filter(pk=par_id).first()
                if par and not par.items.exists():
                    par.delete()

            for ics_id in ics_ids:
                ics = InventoryCustodianSlip.objects.filter(pk=ics_id).first()
                if ics and not ics.items.exists():
                    ics.delete()

            if self.qr_code:
                self.qr_code.delete(save=False)

            super().delete()

        AuditLog.objects.create(
            user=deleted_by,
            action='DELETE',
            model_name='Equipment',
            object_id=pk,
            details=f'Permanently deleted: {name} ({pk})',
        )


class EquipmentAssignmentHistory(models.Model):
    """Record of assigned-user changes for an equipment item."""
    equipment = models.ForeignKey(
        Equipment, on_delete=models.CASCADE, related_name='assignment_history'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='equipment_assignments'
    )
    user_name = models.CharField(max_length=200, help_text='Snapshot of assignee name at change time')
    previous_user_name = models.CharField(max_length=200, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='equipment_assignment_changes'
    )
    notes = models.CharField(max_length=50, blank=True, help_text='e.g. Assigned, Reassigned, Unassigned')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-assigned_at']
        verbose_name_plural = 'equipment assignment histories'

    def __str__(self):
        prop_no = self.equipment_id or '—'
        return f"{prop_no}: {self.previous_user_name or '—'} → {self.user_name}"


class PropertyAcknowledgmentReceipt(models.Model):
    """Property Acknowledgment Receipt (COA Circular 2024-006 Annex A.1) for PPE issuance."""
    STATUS_ACTIVE = 'Active'
    STATUS_DUE = 'Due for Renewal'
    STATUS_SUPERSEDED = 'Superseded'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_DUE, 'Due for Renewal'),
        (STATUS_SUPERSEDED, 'Superseded'),
    ]

    lgu = models.CharField(max_length=200)
    fund = models.CharField(max_length=50)
    par_no = models.CharField(max_length=20, unique=True)
    end_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='par_receipts',
        null=True, blank=True,
        help_text='Accountable end-user. Blank until the item is assigned.',
    )
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='par_issued',
    )
    date_received = models.DateField(help_text='Date end-user acknowledges receipt')
    date_issued = models.DateField(help_text='Date custodian issues the PAR')
    renewal_due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=50, null=True, blank=True)
    superseded_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='supersedes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_issued', '-par_no']
        verbose_name = 'Property Acknowledgment Receipt'
        verbose_name_plural = 'Property Acknowledgment Receipts'

    def __str__(self):
        return f'PAR {self.par_no} — {self.end_user or "Unassigned"}'

    def refresh_status(self, save=True):
        """Update status based on renewal date (skip if already superseded)."""
        if self.status == self.STATUS_SUPERSEDED:
            return self.status
        today = timezone.now().date()
        new_status = (
            self.STATUS_DUE if self.renewal_due_date <= today else self.STATUS_ACTIVE
        )
        if new_status != self.status:
            self.status = new_status
            if save:
                self.save(update_fields=['status'])
        return self.status


class PropertyAcknowledgmentReceiptItem(models.Model):
    """Line item on a PAR — data pulled from Equipment at issuance time."""
    par = models.ForeignKey(
        PropertyAcknowledgmentReceipt, on_delete=models.CASCADE, related_name='items',
    )
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name='par_items',
    )
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default='unit')
    description = models.CharField(max_length=500)
    property_number = models.CharField(max_length=50)
    date_acquired = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['pk']

    def __str__(self):
        return f'{self.property_number} — {self.description[:40]}'


class InventoryCustodianSlip(models.Model):
    """Inventory Custodian Slip (COA Circular 2022-004 Appendix 59) for semi-expendable issuance."""
    STATUS_ACTIVE = 'Active'
    STATUS_SUPERSEDED = 'Superseded'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_SUPERSEDED, 'Superseded'),
    ]

    lgu = models.CharField(max_length=200)
    entity_name = models.CharField(
        max_length=200,
        help_text='Office / department receiving the property',
    )
    fund_cluster = models.CharField(max_length=20, blank=True, default='')
    fund = models.CharField(max_length=50)
    ics_no = models.CharField(max_length=30, unique=True)
    supplier_name = models.CharField(max_length=200, blank=True, default='')
    supplier_address = models.CharField(max_length=300, blank=True, default='')
    po_number = models.CharField(max_length=50, blank=True, default='')
    date = models.DateField(help_text='ICS date')
    mode_of_procurement = models.CharField(max_length=100, blank=True, default='')
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='ics_received',
    )
    received_from = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='ics_issued',
    )
    received_by_position = models.CharField(max_length=200, blank=True, default='')
    received_from_position = models.CharField(max_length=200, blank=True, default='')
    date_received_by = models.DateField(null=True, blank=True)
    date_received_from = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=50, null=True, blank=True)
    superseded_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='supersedes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-ics_no']
        verbose_name = 'Inventory Custodian Slip'
        verbose_name_plural = 'Inventory Custodian Slips'

    def __str__(self):
        return f'ICS {self.ics_no} — {self.entity_name}'


class InventoryCustodianSlipItem(models.Model):
    """Line item on an ICS — data pulled from Equipment at issuance time."""
    ics = models.ForeignKey(
        InventoryCustodianSlip, on_delete=models.CASCADE, related_name='items',
    )
    equipment = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, related_name='ics_items',
    )
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default='unit')
    description = models.CharField(max_length=500)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='Line amount (same as total cost for single items)',
    )
    inventory_item_no = models.CharField(max_length=50)
    estimated_unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)
    useful_life = models.PositiveIntegerField(default=5)

    class Meta:
        ordering = ['pk']

    def __str__(self):
        return f'{self.inventory_item_no} — {self.description[:40]}'
