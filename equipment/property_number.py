"""Auto-generate property numbers for equipment registration."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .coa import (
    CLASSIFICATION_LOW,
    CLASSIFICATION_PPE,
    CLASSIFICATION_SEMI,
    preview_coa_classification,
)

FORM_TYPE_PREFIXES = ('PAR', 'ICS', 'SPC', 'SPLC')


def _site_settings():
    try:
        from core.models import SiteSettings
        return SiteSettings.get_solo()
    except Exception:
        return None


def _use_legacy_lgu_code():
    site = _site_settings()
    return bool(site and site.property_number_use_legacy_lgu_code)


def _lgu_code():
    site = _site_settings()
    if site and site.property_number_lgu_code:
        return str(site.property_number_lgu_code).strip()
    return str(getattr(settings, 'LGU_CODE', '1042')).strip()


def _lgu_label():
    """Municipality label for PAR-style property numbers (LGU-{Municipality})."""
    site = _site_settings()
    if site:
        return site.property_number_lgu_label
    municipality = getattr(settings, 'LGU_MUNICIPALITY', 'SUDIPEN')
    name = str(municipality).strip().title()
    return f'LGU-{name}' if name else 'LGU'


def _property_number_lgu_prefix():
    """LGU code prefix. Used only when legacy mode is enabled."""
    if not _use_legacy_lgu_code():
        return ''
    return _lgu_code()


def property_number_prefix(acquisition_cost=None, *, category=None):
    """Return the LGU prefix used at the start of new property numbers."""
    del acquisition_cost, category
    return _property_number_lgu_prefix()


def _segment_value(value, default='00'):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _fund_cluster_code(fund_source):
    code = _segment_value(getattr(fund_source, 'code', None), '000')
    if code.isdigit():
        return code.zfill(3)[-3:]
    return code.upper()


def _classification_code(category):
    if category is None:
        return 'XX'
    code = (getattr(category, 'property_type_code', None) or '').strip().upper()
    if code in FORM_TYPE_PREFIXES:
        return 'XX'
    if code:
        return code
    return 'XX'


def _category_form_type_override(category):
    """Use category fields when they name a COA form prefix (PAR/ICS/SPC/SPLC)."""
    if category is None:
        return None
    for attr in ('property_type_code', 'code', 'name'):
        value = (getattr(category, attr, None) or '').strip().upper()
        if value in FORM_TYPE_PREFIXES:
            return value
        for prefix in FORM_TYPE_PREFIXES:
            if value.startswith(prefix + '-') or value.startswith(prefix + ' '):
                return prefix
    return None


def _form_type_prefix(*, acquisition_cost=None, category=None):
    """
    First segment of property numbers — PAR, ICS, SPC, or SPLC.

    Category ``property_type_code`` may force the prefix. Otherwise COA rules apply:
    PPE → PAR, Low-Value Semi-Expendable → ICS, Semi-Expendable → SPC.
    SPLC is used only when set explicitly on the category.
    """
    override = _category_form_type_override(category)
    if override:
        return override

    coa_preview = preview_coa_classification(
        acquisition_cost=acquisition_cost,
        category_id=getattr(category, 'pk', None),
    )
    classification = coa_preview['classification']
    if classification == CLASSIFICATION_PPE:
        return 'PAR'
    if classification == CLASSIFICATION_LOW:
        return 'ICS'
    if classification == CLASSIFICATION_SEMI:
        return 'SPC'
    return 'ICS'


def _split_property_number(property_number):
    """
    Return (prefix, fund, year, classification, sequence).

    The last four segments are fund, year, classification, and sequence.
    Everything before that is the prefix, which may itself contain hyphens
    (``LGU-SANTOL`` or ``0621``).
    """
    if not property_number or '-' not in str(property_number):
        return None
    parts = str(property_number).split('-')
    if len(parts) < 5:
        return None
    fund, year, classification, sequence = parts[-4:]
    if len(year) != 4 or not year.isdigit() or not sequence.isdigit():
        return None
    prefix = '-'.join(parts[:-4]).strip()
    if not prefix:
        return None
    return prefix, fund, year, classification, int(sequence)


def _acquisition_key(fund, year, classification):
    return f'{fund}-{year}-{classification}'.casefold()


def _acquisition_key_from_number(property_number):
    parsed = _split_property_number(property_number)
    if not parsed:
        return ''
    _prefix, fund, year, classification, _sequence = parsed
    return _acquisition_key(fund, year, classification)


def _acquisition_key_from_base(base):
    parts = (base or '').split('-')
    if len(parts) < 3:
        return ''
    return _acquisition_key(parts[-3], parts[-2], parts[-1])


def _parse_cost(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _parse_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return timezone.now().date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return timezone.now().date()
    return timezone.now().date()


def _parse_property_number_suffix(property_number, lgu_prefix=None):
    """Return (year, sequence) from a property number, or None if not parseable."""
    parsed = _split_property_number(property_number)
    if not parsed:
        return None
    prefix, _fund, year, _classification, sequence = parsed
    if lgu_prefix and prefix.casefold() != str(lgu_prefix).strip().casefold():
        return None
    return year, sequence


def _next_sequence(*, purchase_date=None, form_prefix=None, lgu_label=None, exclude_pk=None):
    """
    Return the next 4-digit sequence for the active LGU prefix in this year.

    The counter is shared across fund sources and classifications. It resets
    each calendar year (first item is 0001). ``form_prefix`` is accepted for
    callers that still pass the COA form type and is not part of the number.
    """
    from .models import Equipment

    del form_prefix  # sequence follows the LGU prefix, not the COA form type
    lgu_prefix = (lgu_label or _property_number_lgu_prefix() or '').strip().casefold()
    year = f'{_parse_date(purchase_date).year:04d}'

    qs = Equipment.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    max_seq = None
    for property_number in qs.values_list('property_number', flat=True):
        parsed = _split_property_number(property_number)
        if not parsed:
            continue
        prefix, _fund, prop_year, _classification, seq = parsed
        if prop_year != year:
            continue
        if lgu_prefix and prefix.casefold() != lgu_prefix:
            continue
        max_seq = seq if max_seq is None else max(max_seq, seq)
    if max_seq is None:
        return 1
    return max_seq + 1


def _prefix_of_base(base):
    """Return the leading prefix of a base (everything before fund-year-classification)."""
    parts = (base or '').split('-')
    if len(parts) <= 3:
        return (base or '').strip()
    return '-'.join(parts[:-3])


def _property_number_base(
    *,
    purchase_date=None,
    fund_source=None,
    category=None,
    acquisition_cost=None,
):
    """
    Return everything but the sequence.

    Legacy mode on: {LGU_CODE}-{FUND}-{YEAR}-{CLASSIFICATION}
    Legacy mode off: {FORM}-{FUND}-{YEAR}-{CLASSIFICATION} (PAR, ICS, SPC, or SPLC)
    """
    fund_cluster = _fund_cluster_code(fund_source)
    year = f'{_parse_date(purchase_date).year:04d}'
    classification = _classification_code(category)
    tail = f'{fund_cluster}-{year}-{classification}'
    if _use_legacy_lgu_code():
        return f'{_lgu_code() or "LGU"}-{tail}'
    form_prefix = _form_type_prefix(acquisition_cost=acquisition_cost, category=category)
    return f'{form_prefix}-{tail}'


def generate_property_number(
    *,
    acquisition_cost=None,
    purchase_date=None,
    fund_source=None,
    category=None,
    department=None,
    exclude_pk=None,
    current_property_number=None,
):
    """
    Build a property number from equipment attributes.

    Legacy mode off (normal): {FORM}-{FUND}-{YEAR}-{CLASSIFICATION}-{SEQUENCE}
    Example: PAR-201-2027-PR-0001

    Legacy mode on: {LGU_CODE}-{FUND}-{YEAR}-{CLASSIFICATION}-{SEQUENCE}
    Examples: LGU-SANTOL-201-2027-PR-0001, 0621-201-2027-PR-0001

    The sequence increments once per prefix and year, shared across fund
    sources and classifications, and resets each calendar year (0001).

    When ``current_property_number`` is provided and its fund, year, and
    classification are unchanged, the existing number is kept so editing
    unrelated fields never renumbers the item.
    """
    numbers = generate_property_numbers(
        count=1,
        acquisition_cost=acquisition_cost,
        purchase_date=purchase_date,
        fund_source=fund_source,
        category=category,
        department=department,
        exclude_pk=exclude_pk,
        current_property_number=current_property_number,
    )
    return numbers[0]


def generate_property_numbers(
    *,
    count=1,
    acquisition_cost=None,
    purchase_date=None,
    fund_source=None,
    category=None,
    department=None,
    exclude_pk=None,
    current_property_number=None,
):
    """
    Build ``count`` consecutive property numbers for individual unit registration.

    Used when Quantity > 1 so each physical unit gets its own control number.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, 500))

    base = _property_number_base(
        purchase_date=purchase_date,
        fund_source=fund_source,
        category=category,
        acquisition_cost=acquisition_cost,
    )
    current_key = _acquisition_key_from_number(current_property_number)
    if (
        count == 1
        and current_property_number
        and current_key
        and current_key == _acquisition_key_from_base(base)
    ):
        return [current_property_number]

    sequence = _next_sequence(
        purchase_date=purchase_date,
        lgu_label=_prefix_of_base(base),
        exclude_pk=exclude_pk,
    )
    return [f'{base}-{(sequence + offset):04d}' for offset in range(count)]


def save_new_equipment_with_property_number(instance, *, max_attempts=25):
    """
    Insert new equipment with a collision-safe, auto-incremented control number.

    The control number (last segment) increments once per LGU prefix and year, shared
    across all categories, and resets to 0001 when the year changes. Because ``property_number`` is the primary
    key, this forces an INSERT so a duplicate control number raises an error
    instead of silently overwriting an existing record. On collision (e.g. two
    users registering at the same time) it regenerates the next number and
    retries.
    """
    from .models import Equipment  # noqa: F401  (ensures app is loaded)

    last_error = None
    for _ in range(max_attempts):
        instance.property_number = generate_property_number(
            acquisition_cost=instance.acquisition_cost or instance.purchase_cost,
            purchase_date=instance.purchase_date,
            fund_source=instance.fund_source,
            category=instance.category,
            department=instance.department,
        )
        try:
            with transaction.atomic():
                instance.save(force_insert=True)
            return instance
        except IntegrityError as exc:
            last_error = exc
            instance._state.adding = True
            continue
    raise last_error


def property_number_is_taken(property_number, *, exclude_pk=None):
    """Return True if another equipment record already uses this property number."""
    from .models import Equipment

    value = (property_number or '').strip()
    if not value:
        return False
    qs = Equipment.objects.filter(property_number__iexact=value)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def _rewrite_copied_property_numbers(old_pk, new_number):
    """Keep printed PAR/ICS copies and audit links on the renamed property number."""
    from core.models import AuditLog

    from .models import InventoryCustodianSlipItem, PropertyAcknowledgmentReceiptItem

    PropertyAcknowledgmentReceiptItem.objects.filter(
        equipment_id=new_number,
    ).update(property_number=new_number)
    InventoryCustodianSlipItem.objects.filter(
        equipment_id=new_number,
    ).update(inventory_item_no=new_number)
    AuditLog.objects.filter(
        model_name='Equipment',
        object_id=old_pk,
    ).update(object_id=new_number)


def _active_property_prefix(equipment):
    """Prefix required by the current Site settings Property Number option."""
    if _use_legacy_lgu_code():
        return _lgu_code() or 'LGU'
    return _form_type_prefix(
        acquisition_cost=getattr(equipment, 'acquisition_cost', None) or getattr(equipment, 'purchase_cost', None),
        category=getattr(equipment, 'category', None),
    )


def property_number_for_current_settings(equipment):
    """
    Property number for this equipment under the current Site settings.

    Fund, year, classification, and sequence stay as recorded. Only the prefix
    changes: the LGU code when legacy mode is on, otherwise PAR/ICS/SPC/SPLC.
    """
    parsed = _split_property_number(getattr(equipment, 'property_number', None) or getattr(equipment, 'pk', None))
    prefix = _active_property_prefix(equipment)
    if not parsed:
        base = _property_number_base(
            purchase_date=equipment.purchase_date,
            fund_source=equipment.fund_source,
            category=equipment.category,
            acquisition_cost=equipment.acquisition_cost or equipment.purchase_cost,
        )
        sequence = _next_sequence(
            purchase_date=equipment.purchase_date,
            lgu_label=_prefix_of_base(base),
            exclude_pk=equipment.pk,
        )
        return f'{base}-{sequence:04d}'
    _prefix, fund, year, classification, sequence = parsed
    return f'{prefix}-{fund}-{year}-{classification}-{sequence:04d}'


def sync_equipment_property_numbers():
    """
    Rename inventory property numbers so the equipment list matches Site settings.

    Returns the number of equipment records renamed.
    """
    import uuid

    from .models import Equipment

    equipment_list = list(
        Equipment.objects.select_related('category', 'fund_source')
    )
    taken = set()
    pending = []
    for equipment in equipment_list:
        target = property_number_for_current_settings(equipment)
        if equipment.pk == target:
            taken.add(target)
        else:
            pending.append((equipment, target))

    changes = []
    for equipment, target in pending:
        base = target.rsplit('-', 1)[0]
        sequence = int(target.rsplit('-', 1)[-1])
        while target in taken and sequence < 10000:
            sequence += 1
            target = f'{base}-{sequence:04d}'
        taken.add(target)
        if equipment.pk != target:
            changes.append((equipment, target))

    if not changes:
        return 0

    with transaction.atomic():
        staged = []
        for equipment, target in changes:
            temp_number = f'TMP{uuid.uuid4().hex[:16]}'
            moved = rekey_equipment_to_property_number(
                equipment, temp_number, old_pk=equipment.pk, refresh_qr=False,
            )
            staged.append((moved, target))
        for equipment, target in staged:
            rekey_equipment_to_property_number(
                equipment, target, old_pk=equipment.pk,
            )
    return len(staged)


def _perform_equipment_rekey(equipment, new_number, *, old_pk, refresh_qr=True):
    """
    Atomically move equipment to ``new_number`` and repoint all related FKs.

    ``equipment`` must already carry the field values to persist. The old row is
    deleted after related records are updated.
    """
    from .models import Equipment

    new_number = (new_number or '').strip()
    if not new_number:
        raise ValueError('Property number is required.')
    if old_pk == new_number:
        equipment.property_number = new_number
        equipment.pk = new_number
        equipment.save()
        return equipment

    original_created_at = equipment.created_at
    with transaction.atomic():
        equipment.property_number = new_number
        equipment.pk = new_number
        equipment._state.adding = True
        # bulk_create bypasses save()/signals so issuance, audit logs and
        # assignment history are not duplicated during the rename.
        Equipment.objects.bulk_create([equipment])
        if original_created_at is not None:
            Equipment.objects.filter(pk=new_number).update(
                created_at=original_created_at,
            )
        for rel in Equipment._meta.related_objects:
            field = rel.field
            if not getattr(field, 'many_to_one', False):
                continue
            attname = field.attname
            rel.related_model._base_manager.filter(
                **{attname: old_pk}
            ).update(**{attname: new_number})
        _rewrite_copied_property_numbers(old_pk, new_number)
        Equipment._base_manager.filter(pk=old_pk).delete()
    if refresh_qr:
        equipment.ensure_qr_code_current()
    return equipment


def rekey_equipment_to_property_number(equipment, new_number, *, old_pk=None, refresh_qr=True):
    """
    Rename equipment to an explicit property number (manual admin edit).

    Returns the equipment instance with its updated primary key.
    """
    old_pk = old_pk or equipment.pk
    new_number = (new_number or '').strip()
    if old_pk == new_number:
        equipment.property_number = new_number
        equipment.pk = new_number
        equipment.save()
        return equipment
    if property_number_is_taken(new_number, exclude_pk=old_pk):
        raise IntegrityError(f'Property number "{new_number}" is already in use.')
    return _perform_equipment_rekey(
        equipment, new_number, old_pk=old_pk, refresh_qr=refresh_qr,
    )


def rekey_equipment_for_edit(equipment, *, max_attempts=25):
    """
    After an equipment edit, rename its property number (the primary key) when
    fund, year, or classification changed.

    The rename is done atomically: a copy is inserted under the new number, every
    linked record (assignment history, PAR/ICS items, accounting entries,
    maintenance and borrow requests) is repointed to it, then the old row is
    removed. If fund, year, and classification are unchanged the number is kept,
    including numbers created under an older prefix.

    Returns the equipment instance (with its possibly-updated primary key).
    """
    old_pk = equipment.pk
    base = _property_number_base(
        purchase_date=equipment.purchase_date,
        fund_source=equipment.fund_source,
        category=equipment.category,
        acquisition_cost=equipment.acquisition_cost or equipment.purchase_cost,
    )
    old_key = _acquisition_key_from_number(old_pk)
    if old_pk and old_key and old_key == _acquisition_key_from_base(base):
        aligned = property_number_for_current_settings(equipment)
        if aligned == old_pk:
            return equipment
        return rekey_equipment_to_property_number(equipment, aligned, old_pk=old_pk)

    last_error = None
    for _ in range(max_attempts):
        sequence = _next_sequence(
            purchase_date=equipment.purchase_date,
            lgu_label=_prefix_of_base(base),
            exclude_pk=old_pk,
        )
        new_number = f'{base}-{sequence:04d}'
        try:
            return _perform_equipment_rekey(equipment, new_number, old_pk=old_pk)
        except IntegrityError as exc:
            last_error = exc
            equipment.property_number = old_pk
            equipment.pk = old_pk
            continue

    equipment.property_number = old_pk
    equipment.pk = old_pk
    if last_error:
        raise last_error
    return equipment


def preview_property_number(
    *,
    acquisition_cost=None,
    purchase_date=None,
    fund_source_id=None,
    category_id=None,
    department_id=None,
    exclude_pk=None,
    current_property_number=None,
    count=1,
):
    """Resolve related objects and return generated property number(s)."""
    from .models import Category, FundSource

    fund_source = None
    category = None

    if fund_source_id:
        fund_source = FundSource.objects.filter(pk=fund_source_id).first()
    if category_id:
        category = Category.objects.filter(pk=category_id).first()

    property_numbers = generate_property_numbers(
        count=count,
        acquisition_cost=acquisition_cost,
        purchase_date=purchase_date,
        fund_source=fund_source,
        category=category,
        exclude_pk=exclude_pk,
        current_property_number=current_property_number,
    )
    property_number = property_numbers[0]

    coa_preview = preview_coa_classification(
        acquisition_cost=acquisition_cost,
        category_id=category_id,
    )
    form_prefix = _form_type_prefix(acquisition_cost=acquisition_cost, category=category)

    return {
        'property_number': property_number,
        'property_numbers': property_numbers,
        'count': len(property_numbers),
        'prefix': form_prefix,
        'form_prefix': form_prefix,
        'lgu_code': _lgu_code(),
        'lgu_name': _property_number_lgu_prefix(),
        'lgu_label': _lgu_label(),
        'use_legacy_lgu_code': _use_legacy_lgu_code(),
        'fund_cluster': _fund_cluster_code(fund_source),
        'year_acquired': f'{_parse_date(purchase_date).year:04d}',
        'classification_code': _classification_code(category),
        'form_type': form_prefix,
        'coa_classification': coa_preview['classification'],
        'ppe_threshold': coa_preview['ppe_threshold'],
    }
