"""Property, Plant and Equipment Ledger Card (COA Appendix 70).

Depreciation follows the municipal computation sheet:

* Depreciable amount = acquisition cost × depreciable percent (default 95%).
* Annual depreciation = depreciable amount / useful life in years.
* A purchase on days 1–15 starts depreciation in that month.
* A purchase on day 16 or later starts on the first day of the next month.
* The first and last calendar years are prorated by month. Full years post on 31 December.
* Equipment repair records appear as Repair History lines and do not change cost.
"""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

DASH = ' - '
_CENT = Decimal('0.01')


def depreciation_start_date(purchase_date):
    """First day of the month depreciation begins."""
    if purchase_date.day <= 15:
        return date(purchase_date.year, purchase_date.month, 1)
    if purchase_date.month == 12:
        return date(purchase_date.year + 1, 1, 1)
    return date(purchase_date.year, purchase_date.month + 1, 1)


def iter_depreciation_periods(purchase_date, useful_life_years):
    """Yield ``(period_end, months)`` covering the useful life."""
    start = depreciation_start_date(purchase_date)
    remaining = int(useful_life_years) * 12
    year = start.year
    month = start.month
    while remaining > 0:
        available = 12 - month + 1
        take = min(remaining, available)
        end_month = month + take - 1
        last_day = calendar.monthrange(year, end_month)[1]
        yield date(year, end_month, last_day), take
        remaining -= take
        year += 1
        month = 1


def period_charges(cost, useful_life_years, depreciable_percent, periods):
    """Return ``(charges, annual, depreciable_base)`` in pesos, rounded to centavos.

    The final period absorbs rounding so accumulated depreciation equals the
    depreciable amount.
    """
    cost = Decimal(str(cost or 0))
    life = int(useful_life_years or 0)
    percent = Decimal(str(depreciable_percent or 0))
    base = (cost * percent / Decimal('100')).quantize(_CENT, rounding=ROUND_HALF_UP)
    periods = list(periods)
    if life <= 0 or base <= 0 or not periods:
        return [], Decimal('0.00'), base

    annual = (base / Decimal(life)).quantize(_CENT, rounding=ROUND_HALF_UP)
    charges = []
    accumulated = Decimal('0.00')
    last_index = len(periods) - 1
    for index, (_end, months) in enumerate(periods):
        if index == last_index:
            charge = (base - accumulated).quantize(_CENT, rounding=ROUND_HALF_UP)
        else:
            charge = (annual * Decimal(months) / Decimal(12)).quantize(_CENT, rounding=ROUND_HALF_UP)
        remaining = base - accumulated
        if charge > remaining:
            charge = remaining
        if charge < 0:
            charge = Decimal('0.00')
        charges.append(charge)
        accumulated += charge
    return charges, annual, base


def months_recognized(purchase_date, useful_life_years, as_of):
    """Months of depreciation elapsed from the start month through ``as_of``."""
    if not purchase_date or not as_of or not useful_life_years:
        return 0
    start = depreciation_start_date(purchase_date)
    if as_of < start:
        return 0
    total = int(useful_life_years) * 12
    elapsed = (as_of.year - start.year) * 12 + (as_of.month - start.month) + 1
    return max(0, min(elapsed, total))


def accumulated_for_months(charges, periods, months, depreciable_base):
    """Accumulated depreciation after ``months`` of the schedule, including a partial period."""
    remaining = int(months or 0)
    total = Decimal('0.00')
    base = Decimal(str(depreciable_base or 0))
    for charge, (_end, period_months) in zip(charges, periods):
        if remaining <= 0:
            break
        if remaining >= period_months:
            total += charge
            remaining -= period_months
        else:
            partial = (charge * Decimal(remaining) / Decimal(period_months)).quantize(
                _CENT, rounding=ROUND_HALF_UP,
            )
            total += partial
            remaining = 0
    if total > base:
        return base
    return total.quantize(_CENT, rounding=ROUND_HALF_UP)


def depreciation_rate_label(useful_life_years):
    """Straight-line rate label, e.g. ``10%`` for a 10-year life."""
    life = int(useful_life_years or 0)
    if life <= 0:
        return ''
    rate = (Decimal(100) / Decimal(life)).quantize(_CENT, rounding=ROUND_HALF_UP)
    text = format(rate, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return f'{text}%'


def _money(value):
    return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _province_line(site):
    raw = (getattr(site, 'lgu_province', '') or '').strip()
    if raw.lower().startswith('province of '):
        raw = raw[12:].strip()
    name = raw.title() if raw else 'La Union'
    return f'Province of {name}'


def _municipality_line(site):
    raw = (getattr(site, 'lgu_municipality', '') or '').strip()
    name = raw.upper() if raw else 'SANTOL'
    return f'MUNICIPALITY OF {name}'


def _fund_cluster_label(equipment):
    if getattr(equipment, 'fund_source_id', None) and equipment.fund_source_id:
        source = equipment.fund_source
        code = (source.code or '').strip()
        name = (source.name or '').strip()
        if code and name:
            return f'{code}- {name}'
        return name or code
    return (equipment.fund or '').strip()


def _object_account_code(equipment):
    from reports.inventory_excel import CATEGORY_CODE_TO_PPE, _format_uacs_code

    category = equipment.category if getattr(equipment, 'category_id', None) else None
    if category is not None:
        mapped = CATEGORY_CODE_TO_PPE.get(category.code, '')
        if mapped:
            return mapped
    return _format_uacs_code(getattr(equipment, 'coa_account_code', '') or '')


def _present(value):
    text = (value or '').strip()
    if text.lower() in {'n/a', 'na', 'none', '-', '—'}:
        return ''
    return text


def _description(equipment):
    custom = _present(equipment.description)
    name = equipment.display_name if hasattr(equipment, 'display_name') else (equipment.name or '')
    if custom:
        text = custom
    else:
        parts = []
        if name:
            parts.append(name)
        brand_model = ' '.join(
            part for part in (_present(equipment.brand), _present(equipment.model)) if part
        )
        if brand_model and brand_model.lower() not in name.lower():
            parts.append(brand_model)
        text = '; '.join(parts)
    serial = _present(equipment.serial_number)
    if serial and serial.lower() not in text.lower():
        text = f'{text}; Serial No. {serial}' if text else f'Serial No. {serial}'
    return text


def _remarks(equipment):
    if getattr(equipment, 'property_status_id', None) and equipment.property_status_id:
        name = (equipment.property_status.name or '').strip()
        if name.lower() == 'working':
            return 'In good condition'
        if name:
            return name
    status = (equipment.status or '').strip()
    if status.lower() in ('available', 'working'):
        return 'In good condition'
    return status


def _officer_name(equipment):
    if not getattr(equipment, 'assigned_user_id', None) or not equipment.assigned_user_id:
        return ''
    user = equipment.assigned_user
    return (user.get_full_name() or '').strip() or user.username


def _office_name(equipment):
    if getattr(equipment, 'department_id', None) and equipment.department_id:
        return (equipment.department.name or '').strip()
    return (equipment.current_location or '').strip()


def _completed_repairs(equipment):
    """Repair-history lines for the ledger: date, nature (Minor/Major), amount."""
    related = getattr(equipment, 'repairs', None)
    if related is None:
        return []
    repairs = []
    for repair in related.all():
        if not repair.repair_date:
            continue
        repairs.append((repair.repair_date, repair.nature, _money(repair.amount)))
    return repairs


def _acquisition_cost(equipment):
    cost = equipment.acquisition_cost if equipment.acquisition_cost else equipment.purchase_cost
    return _money(cost)


def _useful_life(equipment):
    return int(equipment.estimated_useful_life or equipment.expected_lifespan_years or 0)


def build_ppe_ledger(equipment, *, as_of=None, site=None):
    """Build the Appendix 70 ledger for one PPE item, including the full-life projection."""
    from django.utils import timezone

    if site is None:
        from core.models import SiteSettings
        site = SiteSettings.get_solo()
    if as_of is None:
        as_of = timezone.now().date()

    cost = _acquisition_cost(equipment)
    life = _useful_life(equipment)
    percent = Decimal(str(getattr(site, 'ppe_depreciable_percent', None) or 95))
    purchase_date = equipment.purchase_date
    qty = int(equipment.quantity or 1) or 1
    unit_cost = (cost / Decimal(qty)).quantize(_CENT, rounding=ROUND_HALF_UP) if qty else cost

    periods = []
    charges = []
    annual = Decimal('0.00')
    depreciable_base = Decimal('0.00')
    if purchase_date and cost > 0 and life > 0 and percent > 0:
        periods = list(iter_depreciation_periods(purchase_date, life))
        charges, annual, depreciable_base = period_charges(cost, life, percent, periods)

    rows = []
    if purchase_date or cost:
        rows.append({
            'date': purchase_date,
            'reference': None,
            'qty': qty,
            'unit_cost': unit_cost,
            'total_cost': cost,
            'depreciation': None,
            'accumulated': DASH,
            'impairment': DASH,
            'adjustment': DASH,
            'adjusted_cost': cost,
            'repair_nature': None,
            'repair_amount': None,
        })

    events = []
    running = Decimal('0.00')
    for (period_end, _months), charge in zip(periods, charges):
        running += charge
        events.append((period_end, 2, {
            'date': period_end,
            'reference': None,
            'qty': None,
            'unit_cost': None,
            'total_cost': None,
            'depreciation': charge,
            'accumulated': running,
            'impairment': None,
            'adjustment': None,
            'adjusted_cost': (cost - running).quantize(_CENT, rounding=ROUND_HALF_UP),
            'repair_nature': None,
            'repair_amount': None,
        }))

    for when, nature, amount in _completed_repairs(equipment):
        if purchase_date and periods:
            recognized = months_recognized(purchase_date, life, when)
            snapshot = accumulated_for_months(charges, periods, recognized, depreciable_base)
            accumulated = snapshot
            adjusted_cost = (cost - snapshot).quantize(_CENT, rounding=ROUND_HALF_UP)
        else:
            accumulated = None
            adjusted_cost = None
        events.append((when, 1, {
            'date': when,
            'reference': None,
            'qty': None,
            'unit_cost': None,
            'total_cost': None,
            'depreciation': None,
            'accumulated': accumulated,
            'impairment': None,
            'adjustment': None,
            'adjusted_cost': adjusted_cost,
            'repair_nature': nature,
            'repair_amount': amount,
        }))

    events.sort(key=lambda item: (item[0], item[1]))
    rows.extend(event[2] for event in events)
    repair_rows = [row for row in rows if row.get('repair_nature')]

    posted = Decimal('0.00')
    for (period_end, _months), charge in zip(periods, charges):
        if period_end <= as_of:
            posted += charge
    book_value = (cost - posted).quantize(_CENT, rounding=ROUND_HALF_UP)

    accountability = purchase_date.strftime('%m/%d/%Y') if purchase_date else ''
    ppe_type = ''
    if getattr(equipment, 'category_id', None) and equipment.category_id:
        ppe_type = equipment.category.name

    return {
        'property_number': equipment.property_number,
        'appendix': 'Appendix 70',
        'republic': 'Republic of the Philippines',
        'province': _province_line(site),
        'municipality': _municipality_line(site),
        'title': 'PROPERTY, PLANT AND EQUIPMENT LEDGER CARD',
        'accountable_office': _office_name(equipment),
        'fund_cluster': _fund_cluster_label(equipment),
        'accountable_officer': _officer_name(equipment),
        'accountability_date': accountability,
        'ppe_type': ppe_type,
        'object_code': _object_account_code(equipment),
        'useful_life': life,
        'useful_life_label': f'{life} Years' if life else '',
        'description': _description(equipment),
        'rate_label': depreciation_rate_label(life),
        'remarks': _remarks(equipment),
        'depreciable_percent': percent,
        'acquisition_cost': cost,
        'annual_depreciation': annual,
        'book_value': book_value,
        'rows': rows,
        'repair_rows': repair_rows,
        'prepared_by_name': (getattr(site, 'ppe_prepared_by_name', '') or '').strip(),
        'prepared_by_position': (getattr(site, 'ppe_prepared_by_position', '') or '').strip(),
        'noted_by_name': (getattr(site, 'ppe_noted_by_name', '') or '').strip(),
        'noted_by_position': (getattr(site, 'ppe_noted_by_position', '') or '').strip(),
    }
