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
    """Active first segment for new property numbers (legacy numeric or LGU-{Municipality})."""
    site = _site_settings()
    if site:
        return site.property_number_prefix_segment
    return _lgu_label()


def _known_property_number_prefixes():
    """Prefixes used when parsing existing property numbers (active + legacy)."""
    prefixes = []
    active = _property_number_lgu_prefix()
    if active:
        prefixes.append(active)
    legacy_code = _lgu_code()
    if legacy_code and legacy_code not in prefixes:
        prefixes.append(legacy_code)
    municipality_label = _lgu_label()
    if municipality_label and municipality_label not in prefixes:
        prefixes.append(municipality_label)
    return prefixes


def property_number_prefix(acquisition_cost=None, *, category=None):
    """Return the COA form prefix used at the start of property numbers."""
    return _form_type_prefix(acquisition_cost=acquisition_cost, category=category)


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


def _parse_form_type_property_number(property_number):
    """Return (form_prefix, year, sequence) for PAR/ICS/SPC/SPLC numbers."""
    if not property_number:
        return None
    parts = property_number.split('-')
    if len(parts) < 5 or parts[0] not in FORM_TYPE_PREFIXES:
        return None
    year = parts[2]
    if len(year) != 4 or not year.isdigit():
        return None
    try:
        sequence = int(parts[-1])
    except ValueError:
        return None
    return parts[0], year, sequence


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
    form_parsed = _parse_form_type_property_number(property_number)
    if form_parsed:
        _form_prefix, year, sequence = form_parsed
        return year, sequence

    prefixes = [lgu_prefix] if lgu_prefix else _known_property_number_prefixes()
    for prefix_label in prefixes:
        if not prefix_label:
            continue
        prefix = f'{prefix_label}-'
        if not property_number or not property_number.startswith(prefix):
            continue
        rest = property_number[len(prefix):]
        parts = rest.split('-')
        if len(parts) < 4:
            continue
        year = parts[1]
        try:
            sequence = int(parts[-1])
        except ValueError:
            continue
        return year, sequence
    return None


def _next_sequence(*, purchase_date=None, form_prefix=None, lgu_label=None, exclude_pk=None):
    """
    Return the next 4-digit sequence for property numbers in the same form type and year.

    The counter is shared across fund sources and categories within the same
    PAR/ICS/SPC/SPLC prefix. It resets each calendar year (first item is 0001).
    """
    from .models import Equipment

    form_prefix = form_prefix or 'PAR'
    lgu_prefix = lgu_label or _property_number_lgu_prefix()
    year = f'{_parse_date(purchase_date).year:04d}'

    qs = Equipment.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    max_seq = None
    for property_number in qs.values_list('property_number', flat=True):
        form_parsed = _parse_form_type_property_number(property_number)
        if form_parsed:
            prop_form, prop_year, seq = form_parsed
            if prop_form == form_prefix and prop_year == year:
                max_seq = seq if max_seq is None else max(max_seq, seq)
            continue

        parsed = _parse_property_number_suffix(property_number, lgu_prefix)
        if parsed is None:
            parsed = _parse_property_number_suffix(property_number)
        if parsed is None:
            continue
        prop_year, seq = parsed
        if prop_year == year:
            max_seq = seq if max_seq is None else max(max_seq, seq)
    if max_seq is None:
        return 1
    return max_seq + 1


def _property_number_base(
    *,
    purchase_date=None,
    fund_source=None,
    category=None,
    acquisition_cost=None,
):
    """Return the {FORM}-{FUND}-{YEAR}-{CLASSIFICATION} prefix (everything but the sequence)."""
    form_prefix = _form_type_prefix(acquisition_cost=acquisition_cost, category=category)
    fund_cluster = _fund_cluster_code(fund_source)
    year = f'{_parse_date(purchase_date).year:04d}'
    classification = _classification_code(category)
    return f'{form_prefix}-{fund_cluster}-{year}-{classification}'


def _base_of(property_number):
    """Return the base prefix of an existing property number (drops the sequence segment)."""
    if not property_number or '-' not in property_number:
        return ''
    return property_number.rsplit('-', 1)[0]


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

    Format: {FORM_TYPE}-{FUND_CODE}-{YEAR}-{CLASSIFICATION}-{SEQUENCE}
    Example: PAR-101-2026-MO-0001, ICS-000-2026-XX-0001

    FORM_TYPE is PAR, ICS, SPC, or SPLC (from category or COA classification).
    The sequence increments once per form type and year. The counter resets each
    calendar year (first item is 0001).

    When ``current_property_number`` is provided and its base prefix is unchanged,
    the existing number is kept as-is so editing unrelated fields never renumbers
    the item.
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
    if (
        count == 1
        and current_property_number
        and _base_of(current_property_number) == base
    ):
        return [current_property_number]

    form_prefix = base.split('-', 1)[0]
    sequence = _next_sequence(
        purchase_date=purchase_date,
        form_prefix=form_prefix,
        exclude_pk=exclude_pk,
    )
    return [f'{base}-{(sequence + offset):04d}' for offset in range(count)]


def save_new_equipment_with_property_number(instance, *, max_attempts=25):
    """
    Insert new equipment with a collision-safe, auto-incremented control number.

    The control number (last segment) increments once per LGU and year, shared
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


def _perform_equipment_rekey(equipment, new_number, *, old_pk):
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
        Equipment._base_manager.filter(pk=old_pk).delete()
    equipment.ensure_qr_code_current()
    return equipment


def rekey_equipment_to_property_number(equipment, new_number, *, old_pk=None):
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
    return _perform_equipment_rekey(equipment, new_number, old_pk=old_pk)


def rekey_equipment_for_edit(equipment, *, max_attempts=25):
    """
    After an equipment edit, rename its property number (the primary key) when
    the base prefix changed because of a new date, fund source, or category.

    The rename is done atomically: a copy is inserted under the new number, every
    linked record (assignment history, PAR/ICS items, accounting entries,
    maintenance and borrow requests) is repointed to it, then the old row is
    removed. If the base prefix is unchanged the number is kept as-is.

    Returns the equipment instance (with its possibly-updated primary key).
    """
    old_pk = equipment.pk
    base = _property_number_base(
        purchase_date=equipment.purchase_date,
        fund_source=equipment.fund_source,
        category=equipment.category,
        acquisition_cost=equipment.acquisition_cost or equipment.purchase_cost,
    )
    if old_pk and _base_of(old_pk) == base:
        return equipment  # nothing acquisition-related changed → keep the number

    form_prefix = base.split('-', 1)[0]
    last_error = None
    for _ in range(max_attempts):
        sequence = _next_sequence(
            purchase_date=equipment.purchase_date,
            form_prefix=form_prefix,
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
