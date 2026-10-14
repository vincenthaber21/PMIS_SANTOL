"""Semi-Expendable Property Card (SPC) — COA Annex A.2 numbering and ledger rows."""
from datetime import date

from .coa import effective_cost
from .property_number import _parse_property_number_suffix


def spc_lgu_name():
    """LGU name for SPC header (Province/City/Municipality)."""
    try:
        from core.models import SiteSettings
        site = SiteSettings.get_solo()
        municipality = (site.lgu_municipality or '').strip().title()
        province = (site.lgu_province or '').strip().upper()
        if municipality and province:
            return f'{municipality}, {province}'
        if municipality:
            return municipality
    except Exception:
        pass
    from .coa import LGU_NAME
    return LGU_NAME


def spc_fund_label(equipment):
    """Fund name per COA — from fund source or stored fund field."""
    if equipment.fund_source_id:
        return equipment.fund_source.name
    return equipment.fund or 'General Fund'


def spc_semi_expendable_type(equipment):
    """Semi-expendable property type (category/class)."""
    if equipment.category_id:
        return equipment.category.name
    return equipment.classification or ''


def spc_property_description(equipment):
    """Description block — brand, model, serial number, etc."""
    parts = [equipment.display_name]
    if equipment.brand or equipment.model:
        parts.append(f'({equipment.brand} {equipment.model})'.strip())
    if equipment.serial_number:
        parts.append(f'S/N: {equipment.serial_number}')
    return ' '.join(parts)


def spc_useful_life_label(equipment):
    """Estimated useful life text for SPC/SPLC header fields."""
    life_years = equipment.estimated_useful_life or equipment.expected_lifespan_years
    if not life_years:
        return ''
    return f'{life_years} year{"s" if life_years != 1 else ""}'


def spc_expiration_date(equipment):
    """Date of expiration from acquisition date + estimated useful life."""
    if not equipment.purchase_date or not equipment.estimated_useful_life:
        return None
    try:
        return equipment.purchase_date.replace(
            year=equipment.purchase_date.year + equipment.estimated_useful_life,
        )
    except ValueError:
        return equipment.purchase_date.replace(
            year=equipment.purchase_date.year + equipment.estimated_useful_life,
            day=28,
        )


def spc_acquisition_order(equipment):
    """
    Order of acquisition within the calendar year of acquisition.

    Derived from the annual control-number sequence on the property number.
    Resets every year per COA SPC instructions.
    """
    parsed = _parse_property_number_suffix(equipment.property_number)
    if parsed:
        _year, sequence = parsed
        return sequence
    return 1


def spc_receipt_item_no(*, qty, order, trans_date):
    """
    Receipt-Item No.: {series/qty}-{order}-{yy}

    Series/quantity · order of acquisition (renewed yearly) · year acquired (last 2 digits).
    """
    qty = max(int(qty or 1), 1)
    order = max(int(order or 1), 1)
    yy = _yy(trans_date)
    return f'{qty}-{order:02d}-{yy:02d}'


def spc_issue_item_no(*, issue_qty, issue_order, trans_date):
    """
    Issue/Transfer/Disposal-Item No.: {issued}-{order}-{yy}

    Number issued · order of acquisition/issue (renewed yearly) · year (last 2 digits).
    Example: 01-01-25
    """
    issue_qty = max(int(issue_qty or 1), 1)
    issue_order = max(int(issue_order or 1), 1)
    yy = _yy(trans_date)
    return f'{issue_qty}-{issue_order:02d}-{yy:02d}'


def _yy(value):
    if isinstance(value, date):
        return value.year % 100
    return date.today().year % 100


def _office_officer_label(*, entity='', officer=''):
    """Format Office/Officer column: agency/entity and accountable person."""
    entity = (entity or '').strip()
    officer = (officer or '').strip()
    if entity and officer:
        return f'{entity} / {officer}'
    return entity or officer


def _borrow_office_officer(borrow_request):
    entity = ''
    if borrow_request.department_id:
        entity = str(borrow_request.department)
    elif borrow_request.equipment.department_id:
        entity = str(borrow_request.equipment.department)
    officer = borrow_request.employee.get_full_name() or borrow_request.employee.username
    return _office_officer_label(entity=entity, officer=officer)


def _assignment_office_officer(equipment, user_name):
    entity = str(equipment.department) if equipment.department_id else ''
    return _office_officer_label(entity=entity, officer=user_name)


def get_spc_transactions(equipment):
    """
    SPC ledger rows from source documents — acquisition, issuance, transfer, disposal.

    Each row includes COA-standard receipt/issue item numbers and office/officer labels.
    """
    from borrowing.models import BorrowRequest

    rows = []
    cost = effective_cost(equipment)
    acquisition_order = spc_acquisition_order(equipment)
    default_qty = equipment.quantity or 1
    issue_orders_by_year = {}
    expiration = spc_expiration_date(equipment)

    def _next_issue_order(trans_date):
        year = trans_date.year
        issue_orders_by_year[year] = issue_orders_by_year.get(year, 0) + 1
        return issue_orders_by_year[year]

    if equipment.purchase_date:
        rows.append({
            'date': equipment.purchase_date,
            'reference': 'IAR',
            'particulars': f'Received — {equipment.name}',
            'receipt_qty': default_qty,
            'issue_qty': 0,
            'balance': default_qty,
            'amount': cost,
            'receipt_item_no': spc_receipt_item_no(
                qty=default_qty,
                order=acquisition_order,
                trans_date=equipment.purchase_date,
            ),
            'issue_item_no': '',
            'office_officer': '',
            'expiration_date': expiration,
        })

    for br in BorrowRequest.objects.filter(
        equipment=equipment,
        approval_status__in=['Approved', 'Returned', 'Overdue'],
    ).select_related('employee', 'department', 'equipment__department').order_by('borrow_date'):
        issue_order = _next_issue_order(br.borrow_date)
        rows.append({
            'date': br.borrow_date,
            'reference': f'BR-{br.pk:04d}',
            'particulars': f'Issued to {br.employee}',
            'receipt_qty': 0,
            'issue_qty': br.quantity or 1,
            'balance': 0,
            'amount': cost,
            'receipt_item_no': '',
            'issue_item_no': spc_issue_item_no(
                issue_qty=br.quantity or 1,
                issue_order=issue_order,
                trans_date=br.borrow_date,
            ),
            'office_officer': _borrow_office_officer(br),
            'expiration_date': None,
        })
        if br.actual_return:
            rows.append({
                'date': br.actual_return,
                'reference': f'BR-{br.pk:04d}-RET',
                'particulars': f'Returned from {br.employee}',
                'receipt_qty': br.quantity or 1,
                'issue_qty': 0,
                'balance': br.quantity or 1,
                'amount': cost,
                'receipt_item_no': spc_receipt_item_no(
                    qty=br.quantity or 1,
                    order=acquisition_order,
                    trans_date=br.actual_return,
                ),
                'issue_item_no': '',
                'office_officer': _borrow_office_officer(br),
                'expiration_date': None,
            })

    for ah in equipment.assignment_history.filter(
        notes__in=('Assigned', 'Reassigned'),
    ).order_by('assigned_at'):
        if not ah.user:
            continue
        trans_date = ah.assigned_at.date()
        issue_order = _next_issue_order(trans_date)
        rows.append({
            'date': trans_date,
            'reference': f'ASG-{ah.pk:04d}',
            'particulars': f'Assigned to {ah.user_name}',
            'receipt_qty': 0,
            'issue_qty': 1,
            'balance': 0,
            'amount': cost,
            'receipt_item_no': '',
            'issue_item_no': spc_issue_item_no(
                issue_qty=1,
                issue_order=issue_order,
                trans_date=trans_date,
            ),
            'office_officer': _assignment_office_officer(equipment, ah.user_name),
            'expiration_date': None,
        })

    if equipment.status == 'Retired':
        trans_date = equipment.updated_at.date()
        issue_order = _next_issue_order(trans_date)
        entity = str(equipment.department) if equipment.department_id else 'Supply/Property Division'
        rows.append({
            'date': trans_date,
            'reference': 'DISPOSAL',
            'particulars': 'Retired / disposed',
            'receipt_qty': 0,
            'issue_qty': default_qty,
            'balance': 0,
            'amount': cost,
            'receipt_item_no': '',
            'issue_item_no': spc_issue_item_no(
                issue_qty=default_qty,
                issue_order=issue_order,
                trans_date=trans_date,
            ),
            'office_officer': entity,
            'expiration_date': None,
        })

    rows.sort(key=lambda r: r['date'])
    return rows
