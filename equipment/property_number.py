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


def unique_property_numbers_enabled():
    """True when each physical unit must receive its own property number."""
    site = _site_settings()
    if site is None:
        return True
    return bool(getattr(site, 'property_number_unique_per_unit', True))


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


def _is_year_segment(value):
    text = str(value or '').strip()
    if len(text) != 4 or not text.isdigit():
        return False
    year = int(text)
    return 1900 <= year <= 2199


def _split_property_number(property_number):
    """
    Parse a property number into a dict, or return None.

    Standard layout: {YEAR}-{CATEGORY}-{ITEM COUNT}-{DEPARTMENT}
    Example: 2027-05-01-001-HRMO
    The category code may itself contain hyphens (``05-01``).

    Legacy layout: {PREFIX}-{FUND}-{YEAR}-{CLASSIFICATION}-{SEQUENCE}
    Example: PAR-201-2027-PR-0001 or LGU-SANTOL-201-2027-PR-0001
    """
    if not property_number or '-' not in str(property_number):
        return None
    parts = str(property_number).split('-')
    if len(parts) < 4:
        return None

    if (
        len(parts) >= 5
        and parts[-1].isdigit()
        and _is_year_segment(parts[-3])
    ):
        fund, year, classification, sequence = parts[-4:]
        prefix = '-'.join(parts[:-4]).strip()
        if not prefix or not sequence.isdigit():
            return None
        return {
            'format': 'legacy',
            'prefix': prefix,
            'fund': fund,
            'year': year,
            'classification': classification,
            'sequence': int(sequence),
            'category': '',
            'department': '',
        }

    if _is_year_segment(parts[0]) and parts[-2].isdigit() and parts[-1].strip():
        category = '-'.join(parts[1:-2]).strip()
        if not category:
            return None
        return {
            'format': 'standard',
            'prefix': '',
            'fund': '',
            'year': parts[0],
            'classification': '',
            'sequence': int(parts[-2]),
            'category': category,
            'department': parts[-1].strip(),
        }
    return None


def _acquisition_key(fund, year, classification):
    return f'{fund}-{year}-{classification}'.casefold()


def _acquisition_key_from_number(property_number):
    parsed = _split_property_number(property_number)
    if not parsed or parsed['format'] != 'legacy':
        return ''
    return _acquisition_key(parsed['fund'], parsed['year'], parsed['classification'])


def _acquisition_key_from_base(base):
    parts = (base or '').split('-')
    if len(parts) < 3:
        return ''
    return _acquisition_key(parts[-3], parts[-2], parts[-1])


def _category_number(category):
    """Category code placed in the property number, e.g. 05-01."""
    code = _segment_value(getattr(category, 'code', None), '00')
    return code.replace(' ', '')


def _department_code(department):
    """Department code at the end of the property number, e.g. HRMO."""
    code = _segment_value(getattr(department, 'code', None), 'XX')
    code = code.replace('-', '').replace(' ', '').upper()
    return code or 'XX'


def _format_item_sequence(sequence):
    sequence = int(sequence)
    if sequence < 0:
        sequence = 0
    return f'{sequence:03d}'


def _format_standard_number(year, category_code, sequence, department_code):
    """year-category-item count-department, e.g. 2027-05-01-001-HRMO."""
    return f'{year}-{category_code}-{_format_item_sequence(sequence)}-{department_code}'


def _standard_parts(*, purchase_date=None, category=None, department=None):
    year = f'{_parse_date(purchase_date).year:04d}'
    return year, _category_number(category), _department_code(department)


def _number_with_sequence(property_number, sequence):
    """Return the same property number with a new item-count / sequence segment."""
    parsed = _split_property_number(property_number)
    if not parsed:
        base = str(property_number).rsplit('-', 1)[0]
        return f'{base}-{int(sequence):04d}'
    if parsed['format'] == 'standard':
        return _format_standard_number(
            parsed['year'], parsed['category'], sequence, parsed['department'],
        )
    return (
        f'{parsed["prefix"]}-{parsed["fund"]}-{parsed["year"]}-'
        f'{parsed["classification"]}-{int(sequence):04d}'
    )


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
    if lgu_prefix:
        if parsed['format'] != 'legacy':
            return None
        if parsed['prefix'].casefold() != str(lgu_prefix).strip().casefold():
            return None
    return parsed['year'], parsed['sequence']


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
        if not parsed or parsed['format'] != 'legacy':
            continue
        if parsed['year'] != year:
            continue
        if lgu_prefix and parsed['prefix'].casefold() != lgu_prefix:
            continue
        seq = parsed['sequence']
        max_seq = seq if max_seq is None else max(max_seq, seq)
    if max_seq is None:
        return 1
    return max_seq + 1


def _next_standard_sequence(*, year, category_code, exclude_pk=None):
    """
    Next 3-digit item count for this year and category.

    The counter is shared by every department and resets each calendar year
    (the first item of a category is 001).
    """
    from .models import Equipment

    year = f'{year}'
    category_key = (category_code or '').strip().casefold()
    qs = Equipment.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    max_seq = None
    for property_number in qs.values_list('property_number', flat=True):
        parsed = _split_property_number(property_number)
        if not parsed or parsed['format'] != 'standard':
            continue
        if parsed['year'] != year or parsed['category'].casefold() != category_key:
            continue
        seq = parsed['sequence']
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
    Return the legacy prefix through classification, without the sequence.

    {LGU_CODE}-{FUND}-{YEAR}-{CLASSIFICATION}
    Used only when legacy LGU numbering is enabled.
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

    Standard layout: {YEAR}-{CATEGORY}-{ITEM COUNT}-{DEPARTMENT}
    Example: 2027-05-01-001-HRMO

    The item count is 001, 002, … for that category in the acquisition year.
    It resets each calendar year. Changing the department keeps the item count
    and only replaces the office code.

    Legacy mode on: {LGU_CODE}-{FUND}-{YEAR}-{CLASSIFICATION}-{SEQUENCE}
    Examples: LGU-SANTOL-201-2027-PR-0001, 0621-201-2027-PR-0001
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
    When unique numbering is turned off in Site settings, every unit shares
    the next single number, so this always returns one value.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, 500))
    if not unique_property_numbers_enabled():
        count = 1

    if not _use_legacy_lgu_code():
        return _generate_standard_property_numbers(
            count=count,
            purchase_date=purchase_date,
            category=category,
            department=department,
            exclude_pk=exclude_pk,
            current_property_number=current_property_number,
        )

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


def _generate_standard_property_numbers(
    *,
    count,
    purchase_date=None,
    category=None,
    department=None,
    exclude_pk=None,
    current_property_number=None,
):
    """year-category-item count-department, e.g. 2027-05-01-001-HRMO."""
    year, category_code, department_code = _standard_parts(
        purchase_date=purchase_date,
        category=category,
        department=department,
    )
    current = _split_property_number(current_property_number) if current_property_number else None
    if count == 1 and current and current['format'] == 'legacy':
        return [str(current_property_number).strip()]
    if (
        count == 1
        and current
        and current['format'] == 'standard'
        and current['year'] == year
        and current['category'].casefold() == category_code.casefold()
    ):
        return [_format_standard_number(
            year, category_code, current['sequence'], department_code,
        )]

    sequence = _next_standard_sequence(
        year=year,
        category_code=category_code,
        exclude_pk=exclude_pk,
    )
    return [
        _format_standard_number(year, category_code, sequence + offset, department_code)
        for offset in range(count)
    ]


def save_new_equipment_with_property_number(instance, *, max_attempts=25):
    """
    Insert new equipment with a collision-safe, auto-incremented control number.

    The item count increments once per category and year, and resets to 001 when the
    year changes. Because ``property_number`` is the primary
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

    Standard mode uses year-category-item count-department. Legacy mode keeps
    fund, year, classification, and sequence, and only swaps the LGU prefix.
    """
    parsed = _split_property_number(
        getattr(equipment, 'property_number', None) or getattr(equipment, 'pk', None)
    )
    if not _use_legacy_lgu_code():
        year, category_code, department_code = _standard_parts(
            purchase_date=equipment.purchase_date,
            category=equipment.category,
            department=equipment.department,
        )
        if (
            parsed
            and parsed['format'] == 'standard'
            and parsed['year'] == year
            and parsed['category'].casefold() == category_code.casefold()
        ):
            return _format_standard_number(
                year, category_code, parsed['sequence'], department_code,
            )
        sequence = _next_standard_sequence(
            year=year,
            category_code=category_code,
            exclude_pk=equipment.pk,
        )
        return _format_standard_number(year, category_code, sequence, department_code)

    prefix = _active_property_prefix(equipment)
    if not parsed or parsed['format'] != 'legacy':
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
    return (
        f'{prefix}-{parsed["fund"]}-{parsed["year"]}-'
        f'{parsed["classification"]}-{parsed["sequence"]:04d}'
    )


def sync_equipment_property_numbers():
    """
    Rename inventory property numbers so the equipment list matches Site settings.

    Returns the number of equipment records renamed.
    """
    import uuid

    from .models import Equipment

    equipment_list = list(
        Equipment.objects.select_related('category', 'fund_source', 'department')
    )
    taken = set()
    used_item_counts = {}
    pending = []

    def _note_number(number):
        parsed = _split_property_number(number)
        if parsed and parsed['format'] == 'standard':
            key = (parsed['year'], parsed['category'].casefold())
            used_item_counts.setdefault(key, set()).add(parsed['sequence'])

    for equipment in equipment_list:
        target = property_number_for_current_settings(equipment)
        if equipment.pk == target:
            taken.add(target)
            _note_number(target)
        else:
            pending.append((equipment, target))

    changes = []
    for equipment, target in pending:
        parsed = _split_property_number(target)
        sequence = parsed['sequence'] if parsed else 1
        key = None
        if parsed and parsed['format'] == 'standard':
            key = (parsed['year'], parsed['category'].casefold())
        while sequence < 10000 and (
            target in taken or (key and sequence in used_item_counts.get(key, ()))
        ):
            sequence += 1
            target = _number_with_sequence(target, sequence)
        taken.add(target)
        _note_number(target)
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
    the year, category, or department changed.

    The item count stays the same when only the department changes. A new item
    count is assigned when the year or category changes. Numbers already stored
    in the legacy layout are left as-is while standard numbering is active.

    Returns the equipment instance (with its possibly-updated primary key).
    """
    old_pk = equipment.pk
    if not _use_legacy_lgu_code():
        parsed = _split_property_number(old_pk)
        if parsed and parsed['format'] == 'legacy':
            return equipment
        year, category_code, department_code = _standard_parts(
            purchase_date=equipment.purchase_date,
            category=equipment.category,
            department=equipment.department,
        )
        if (
            parsed
            and parsed['format'] == 'standard'
            and parsed['year'] == year
            and parsed['category'].casefold() == category_code.casefold()
        ):
            new_number = _format_standard_number(
                year, category_code, parsed['sequence'], department_code,
            )
            if new_number == old_pk:
                return equipment
            return rekey_equipment_to_property_number(equipment, new_number, old_pk=old_pk)

        last_error = None
        for _ in range(max_attempts):
            sequence = _next_standard_sequence(
                year=year,
                category_code=category_code,
                exclude_pk=old_pk,
            )
            new_number = _format_standard_number(
                year, category_code, sequence, department_code,
            )
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
    from .models import Category, Department, FundSource

    fund_source = None
    category = None
    department = None

    if fund_source_id:
        fund_source = FundSource.objects.filter(pk=fund_source_id).first()
    if category_id:
        category = Category.objects.filter(pk=category_id).first()
    if department_id:
        department = Department.objects.filter(pk=department_id).first()

    property_numbers = generate_property_numbers(
        count=count,
        acquisition_cost=acquisition_cost,
        purchase_date=purchase_date,
        fund_source=fund_source,
        category=category,
        department=department,
        exclude_pk=exclude_pk,
        current_property_number=current_property_number,
    )
    property_number = property_numbers[0]

    coa_preview = preview_coa_classification(
        acquisition_cost=acquisition_cost,
        category_id=category_id,
    )
    form_prefix = _form_type_prefix(acquisition_cost=acquisition_cost, category=category)

    unique_per_unit = unique_property_numbers_enabled()
    return {
        'property_number': property_number,
        'property_numbers': property_numbers,
        'count': len(property_numbers),
        'unique_per_unit': unique_per_unit,
        'prefix': form_prefix,
        'form_prefix': form_prefix,
        'lgu_code': _lgu_code(),
        'lgu_name': _property_number_lgu_prefix(),
        'lgu_label': _lgu_label(),
        'use_legacy_lgu_code': _use_legacy_lgu_code(),
        'fund_cluster': _fund_cluster_code(fund_source),
        'year_acquired': f'{_parse_date(purchase_date).year:04d}',
        'category_code': _category_number(category),
        'department_code': _department_code(department),
        'classification_code': _classification_code(category),
        'form_type': form_prefix,
        'coa_classification': coa_preview['classification'],
        'ppe_threshold': coa_preview['ppe_threshold'],
    }
