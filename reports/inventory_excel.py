"""COA inventory Excel export — matches the standard LGU inventory workbook layout."""
import io
from copy import copy
from datetime import date
from pathlib import Path

from django.conf import settings
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from core.models import SiteSettings
from core.signatories import active_supply_officer_user, default_supply_officer_user

TEMPLATE_PATH = Path(__file__).resolve().parent / 'templates' / 'coa_inventory_template.xlsx'

SERVICEABLE_SHEET = '2025 SERVICEABLE'
UNSERVICEABLE_SHEET = '2024 UNSERVICEABLE'

# Order of PPE groups in the COA inventory template (for sorting).
PPE_GROUP_ORDER = [
    '1-07-05-020',
    '1-07-07-010',
    '1-07-05-030',
    '1-07-05-040',
    '1-07-05-070',
    '1-07-05-090',
    '1-07-05-110',
    '1-07-05-130',
    '1-07-06-010',
    '1-07-07-990',
    '1-07-05-080',
    '1-07-99-990',
    '1-07-07-020',
]

# Map equipment category codes to COA PPE UACS codes (matches LGU inventory template).
CATEGORY_CODE_TO_PPE = {
    '05-01': '1-07-07-990',   # Machinery
    '05-02': '1-07-05-020',   # Office Equipment
    '05-03': '1-07-05-030',   # ICT Equipment
    '05-04': '1-07-05-040',   # Agricultural and Forestry Equipment
    '05-05': '1-07-05-050',   # Marine and Fishery Equipment
    '05-06': '1-07-05-060',   # Airport Equipment
    '05-07': '1-07-05-070',   # Multimedia
    '05-08': '1-07-05-090',   # Disaster Response and Rescue Equipment
    '05-09': '1-07-05-100',   # Military, Police and Security Equipment
    '05-10': '1-07-05-110',   # Medical, Dental and Laboratory Equipment
    '05-11': '1-07-05-020',   # Printing Equipment
    '05-12': '1-07-05-130',   # Sports Equipment
    '05-13': '1-07-05-140',   # Technical and Scientific Equipment
    '05-14': '1-07-05-080',   # Construction Equipment
    '05-99': '1-07-06-010',   # Vehicle
    '06-01': '1-07-07-010',   # Furniture
    '06-02': '1-07-07-020',   # Books
    '99-90': '1-07-99-990',   # Other
}

_SUBTOTAL_FILL = PatternFill(fill_type='solid', fgColor='DADADA')
_GRAND_TOTAL_FILL = PatternFill(fill_type='solid', fgColor='8EAADB')
_THIN = Side(style='thin')
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
DATE_ACQUIRED_FORMAT = '[$-409]dd\\-mmm\\-yy'


def _format_uacs_code(code):
    """Format an 8-digit account code as 1-07-05-020."""
    digits = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(digits) == 8:
        return f'{digits[0]}-{digits[1:3]}-{digits[3:5]}-{digits[5:8]}'
    if '-' in str(code or ''):
        return str(code)
    return str(code or '')


def _ppe_sort_key(ppe_code):
    try:
        return PPE_GROUP_ORDER.index(ppe_code)
    except ValueError:
        return len(PPE_GROUP_ORDER)


def _category_subtotal_label(equipment):
    """Build a template-style sub-total label for an equipment category."""
    category = equipment.category
    if not category:
        return 'ZZZZ', 'ZZZZ', 'SUB-TOTAL FOR UNCATEGORIZED'

    ppe_code = _class_code(equipment)
    category_label = category.name.upper()
    if ppe_code:
        return category.code, ppe_code, f'SUB-TOTAL FOR {ppe_code} ({category_label})'
    return category.code, 'ZZZZ', f'SUB-TOTAL FOR {category_label}'


def _class_code(equipment):
    """COA UACS class code for an equipment item (e.g. 1-07-05-020)."""
    category = equipment.category
    if not category:
        return ''
    return CATEGORY_CODE_TO_PPE.get(category.code, '')


def _article_description(equipment):
    """Build the article description shown in column C."""
    parts = [equipment.display_name]
    if equipment.brand and equipment.brand.lower() not in equipment.display_name.lower():
        parts.append(equipment.brand)
    return ' - '.join(dict.fromkeys(parts))


def _office_location(equipment):
    """Office / department location from the database (not assigned personnel)."""
    department_name = equipment.department.name.strip() if equipment.department_id else ''
    current_location = (equipment.current_location or '').strip()

    if department_name and current_location:
        if department_name.casefold() == current_location.casefold():
            return department_name
        return f'{department_name} / {current_location}'
    return department_name or current_location or '—'


def _unit_cost(equipment):
    return float(equipment.acquisition_cost or equipment.purchase_cost or 0)


def _total_cost(equipment):
    qty = equipment.quantity or 1
    return qty * _unit_cost(equipment)


def _write_cost_cell(ws, row, col, value, *, cost_style):
    cell = ws.cell(row, col, value)
    if cost_style:
        cell.font = copy(cost_style['font'])
        cell.border = copy(cost_style['border'])
        cell.alignment = copy(cost_style['alignment'])
        cell.fill = copy(cost_style['fill'])
        cell.number_format = cost_style['number_format']
    return cell


def _capture_date_style(ws, row, col):
    """Capture date-column styling with the standard acquired-date display format."""
    style = _capture_cell_style(ws.cell(row, col))
    style['number_format'] = DATE_ACQUIRED_FORMAT
    return style


def _date_acquired(equipment):
    """Return the equipment purchase date from the database."""
    return equipment.purchase_date


def _write_date_acquired(ws, row, col, equipment, *, date_style):
    """Write date acquired using the template date column formatting."""
    acquired = _date_acquired(equipment)
    cell = ws.cell(row, col)
    if acquired:
        cell.value = acquired
    else:
        cell.value = None
    if date_style:
        cell.font = copy(date_style['font'])
        cell.border = copy(date_style['border'])
        cell.alignment = copy(date_style['alignment'])
        cell.fill = copy(date_style['fill'])
        cell.number_format = date_style['number_format']


def _capture_cell_style(cell):
    return {
        'font': copy(cell.font),
        'border': copy(cell.border),
        'alignment': copy(cell.alignment),
        'fill': copy(cell.fill),
        'number_format': cell.number_format,
    }


def _apply_cell_style(cell, style):
    cell.font = copy(style['font'])
    cell.border = copy(style['border'])
    cell.alignment = copy(style['alignment'])
    cell.fill = copy(style['fill'])
    cell.number_format = style['number_format']


def _group_equipment(equipment_list):
    """Group equipment by category, ordered like the COA inventory template."""
    groups = {}
    for eq in equipment_list:
        category = eq.category
        key = category.pk if category else 0
        if key not in groups:
            cat_code, ppe_code, subtotal_label = _category_subtotal_label(eq)
            groups[key] = {
                'cat_code': cat_code,
                'ppe_code': ppe_code,
                'label': subtotal_label,
                'items': [],
            }
        groups[key]['items'].append(eq)

    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (_ppe_sort_key(groups[k]['ppe_code']), groups[k]['cat_code']),
    )
    result = []
    for key in ordered_keys:
        items = sorted(groups[key]['items'], key=lambda e: e.property_number)
        result.append((groups[key]['label'], items))
    return result


def _trim_trailing_rows(ws, last_row):
    while ws.max_row > last_row:
        ws.delete_rows(ws.max_row, 1)


def _inventory_year():
    today = date.today()
    return today.year if today.month == 12 else today.year


def _inventory_as_of_label():
    return f'as of December 31, {_inventory_year()}'


def _province_line(site):
    province = (site.lgu_province or getattr(settings, 'LGU_PROVINCE', 'LA UNION')).strip()
    if province.lower().startswith('province of'):
        return province.title()
    return f'Province of {province.title()}'


def _municipality_line(site):
    municipality = (site.lgu_municipality or getattr(settings, 'LGU_MUNICIPALITY', 'SUDIPEN')).strip()
    if municipality.lower().startswith('municipality of'):
        return municipality.title()
    return f'Municipality of {municipality.title()}'


def _submitted_by(site, supply_officer=None):
    officer = active_supply_officer_user(user=supply_officer) or default_supply_officer_user()
    if officer:
        name = officer.get_full_name() or officer.username
        position = ''
        if officer.role_id and officer.role.name:
            position = officer.role.name
        elif officer.department_id:
            position = officer.department.name
        return name.upper(), position
    return (
        (site.par_received_from_name or '').upper(),
        site.par_received_from_position or 'Admin. Aide IV/ GSO-Designate',
    )


def _clear_sheet_data(ws, first_data_row):
    stale_merges = [
        str(merged)
        for merged in list(ws.merged_cells.ranges)
        if merged.min_row >= first_data_row
    ]
    for merged_range in stale_merges:
        ws.unmerge_cells(merged_range)
    if ws.max_row >= first_data_row:
        ws.delete_rows(first_data_row, ws.max_row - first_data_row + 1)


def _write_serviceable_rows(ws, equipment_list, *, data_style, date_style, cost_style, subtotal_style, grand_style):
    groups = _group_equipment(equipment_list)
    row = 13

    for subtotal_label, items in groups:
        for eq in items:
            qty = eq.quantity or 1
            unit_cost = _unit_cost(eq)
            total_cost = _total_cost(eq)
            ws.cell(row, 1, qty)
            ws.cell(row, 2, (eq.unit or 'unit').strip())
            ws.cell(row, 3, _article_description(eq))
            ws.cell(row, 4, None)
            _write_date_acquired(ws, row, 5, eq, date_style=date_style)
            ws.cell(row, 6, eq.property_number)
            _write_cost_cell(ws, row, 7, unit_cost, cost_style=cost_style)
            _write_cost_cell(ws, row, 8, total_cost, cost_style=cost_style)
            ws.cell(row, 9, _office_location(eq))
            for col in range(1, 10):
                if col in (5, 7, 8):
                    continue
                _apply_cell_style(ws.cell(row, col), data_style)
            row += 1

        group_total = sum(_total_cost(eq) for eq in items)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        label_cell = ws.cell(row, 1, subtotal_label)
        label_cell.font = Font(bold=True)
        label_cell.alignment = Alignment(horizontal='center', vertical='center')
        total_cell = _write_cost_cell(ws, row, 8, group_total, cost_style=cost_style)
        total_cell.font = Font(bold=True)
        total_cell.alignment = Alignment(horizontal='right', vertical='center')
        for col in range(1, 10):
            cell = ws.cell(row, col)
            cell.fill = copy(subtotal_style['fill'])
            cell.border = copy(subtotal_style['border'])
        row += 1

    grand_total = sum(_total_cost(eq) for eq in equipment_list)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    grand_label = (
        f"GRAND TOTAL OF SERVICEABLE PPE's as of DECEMBER 31, {_inventory_year()}"
    )
    grand_cell = ws.cell(row, 1, grand_label)
    grand_cell.font = Font(bold=True)
    grand_cell.alignment = Alignment(horizontal='center', vertical='center')
    total_cell = _write_cost_cell(ws, row, 8, grand_total, cost_style=cost_style)
    total_cell.font = Font(bold=True)
    total_cell.alignment = Alignment(horizontal='right', vertical='center')
    for col in range(1, 10):
        cell = ws.cell(row, col)
        cell.fill = copy(grand_style['fill'])
        cell.border = copy(grand_style['border'])
    row += 1

    return row


def _write_unserviceable_rows(ws, equipment_list, *, data_style, date_style, cost_style, subtotal_style, grand_style):
    groups = _group_equipment(equipment_list)
    row = 11

    for subtotal_label, items in groups:
        for eq in items:
            qty = eq.quantity or 1
            unit_cost = _unit_cost(eq)
            total_cost = _total_cost(eq)
            ws.cell(row, 1, qty)
            ws.cell(row, 2, (eq.unit or 'unit').strip())
            ws.cell(row, 3, _article_description(eq))
            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=5)
            ws.cell(row, 6, None)
            _write_date_acquired(ws, row, 7, eq, date_style=date_style)
            ws.cell(row, 8, eq.property_number)
            _write_cost_cell(ws, row, 9, unit_cost, cost_style=cost_style)
            _write_cost_cell(ws, row, 10, total_cost, cost_style=cost_style)
            ws.cell(row, 11, _office_location(eq))
            for col in range(1, 12):
                if col in (4, 5, 7, 9, 10):
                    continue
                _apply_cell_style(ws.cell(row, col), data_style)
            _apply_cell_style(ws.cell(row, 6), data_style)
            row += 1

        group_total = sum(_total_cost(eq) for eq in items)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        label_cell = ws.cell(row, 1, subtotal_label)
        label_cell.font = Font(bold=True)
        label_cell.alignment = Alignment(horizontal='center', vertical='center')
        total_cell = _write_cost_cell(ws, row, 10, group_total, cost_style=cost_style)
        total_cell.font = Font(bold=True)
        total_cell.alignment = Alignment(horizontal='right', vertical='center')
        for col in range(1, 12):
            cell = ws.cell(row, col)
            cell.fill = copy(subtotal_style['fill'])
            cell.border = copy(subtotal_style['border'])
        row += 1

    grand_total = sum(_total_cost(eq) for eq in equipment_list)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    grand_label = (
        f"GRAND TOTAL OF UNSERVICEABLE PPE's as of DECEMBER 31, {_inventory_year()}"
    )
    grand_cell = ws.cell(row, 1, grand_label)
    grand_cell.font = Font(bold=True)
    grand_cell.alignment = Alignment(horizontal='center', vertical='center')
    total_cell = _write_cost_cell(ws, row, 10, grand_total, cost_style=cost_style)
    total_cell.font = Font(bold=True)
    total_cell.alignment = Alignment(horizontal='right', vertical='center')
    for col in range(1, 12):
        cell = ws.cell(row, col)
        cell.fill = copy(grand_style['fill'])
        cell.border = copy(grand_style['border'])
    row += 1

    return row


def _write_signature_block(ws, start_row, *, name, position, label_cols=2):
    row = start_row + 3
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=label_cols)
    ws.cell(row, 1, 'Submitted by:').font = Font(bold=True)
    row += 3
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    ws.cell(row, 1, name).font = Font(bold=True)
    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    ws.cell(row, 1, position).font = Font(bold=True)
    return row


def _update_sheet_header(ws, *, title, as_of_col=9):
    site = SiteSettings.get_solo()
    ws.cell(1, 1, 'Repulic of the Philippines')
    ws.cell(2, 1, _province_line(site))
    ws.cell(3, 1, _municipality_line(site))
    ws.cell(6, 1, title)
    ws.cell(7, 1, _inventory_as_of_label())


def _fill_serviceable_sheet(ws, equipment_list, *, supply_officer=None):
    data_style = _capture_cell_style(ws.cell(13, 1))
    date_style = _capture_date_style(ws, 13, 5)
    cost_style = _capture_cell_style(ws.cell(13, 7))
    subtotal_style = _capture_cell_style(ws.cell(40, 1))
    grand_style = _capture_cell_style(ws.cell(200, 1))
    _clear_sheet_data(ws, 13)
    _update_sheet_header(
        ws,
        title='INVENTORY OF SERVICEABLE PROPERTY, PLANT AND EQUIPMENT',
    )
    next_row = _write_serviceable_rows(
        ws,
        equipment_list,
        data_style=data_style,
        date_style=date_style,
        cost_style=cost_style,
        subtotal_style=subtotal_style,
        grand_style=grand_style,
    )
    name, position = _submitted_by(SiteSettings.get_solo(), supply_officer=supply_officer)
    final_row = _write_signature_block(ws, next_row, name=name, position=position)
    _trim_trailing_rows(ws, final_row)


def _fill_unserviceable_sheet(ws, equipment_list, *, supply_officer=None):
    data_style = _capture_cell_style(ws.cell(11, 1))
    date_style = _capture_date_style(ws, 13, 7)
    cost_style = _capture_cell_style(ws.cell(11, 9))
    # Reuse serviceable subtotal / grand styles when template rows are missing.
    subtotal_style = {
        'fill': _SUBTOTAL_FILL,
        'border': _BORDER,
    }
    grand_style = {
        'fill': _GRAND_TOTAL_FILL,
        'border': _BORDER,
    }
    _clear_sheet_data(ws, 11)
    _update_sheet_header(
        ws,
        title='INVENTORY OF UNSERVICEABLE PROPERTY, PLANT AND EQUIPMENT',
        as_of_col=11,
    )
    next_row = _write_unserviceable_rows(
        ws,
        equipment_list,
        data_style=data_style,
        date_style=date_style,
        cost_style=cost_style,
        subtotal_style=subtotal_style,
        grand_style=grand_style,
    )
    name, position = _submitted_by(SiteSettings.get_solo(), supply_officer=supply_officer)
    final_row = _write_signature_block(ws, next_row, name=name, position=position)
    _trim_trailing_rows(ws, final_row)


def _is_serviceable(equipment):
    status_name = (
        equipment.property_status.name.lower()
        if equipment.property_status_id
        else ''
    )
    return status_name not in ('unserviceable', 'disposed', 'condemned')


def _is_unserviceable(equipment):
    status_name = (
        equipment.property_status.name.lower()
        if equipment.property_status_id
        else ''
    )
    return status_name in ('unserviceable', 'disposed', 'condemned')


def generate_inventory_excel(
    equipment_list,
    report_type='property_all',
    supply_officer=None,
):
    """
    Build a COA inventory workbook from the standard template.

    property_all      → serviceable + unserviceable sheets
    property_working  → serviceable sheet only
    property_unserviceable / property_disposed → unserviceable sheet only
    """
    equipment = list(equipment_list)
    if not equipment:
        raise ValueError('No equipment to export.')

    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f'Inventory template not found: {TEMPLATE_PATH}')

    wb = load_workbook(TEMPLATE_PATH)
    year = _inventory_year()

    serviceable_items = [eq for eq in equipment if _is_serviceable(eq)]
    unserviceable_items = [eq for eq in equipment if _is_unserviceable(eq)]

    include_serviceable = report_type in ('property_all', 'property_working')
    include_unserviceable = report_type in (
        'property_all', 'property_unserviceable', 'property_disposed',
    )

    if report_type == 'property_disposed':
        unserviceable_items = [
            eq for eq in equipment
            if eq.property_status_id
            and eq.property_status.name.lower() in ('disposed', 'condemned')
        ]

    if include_serviceable and SERVICEABLE_SHEET in wb.sheetnames:
        ws = wb[SERVICEABLE_SHEET]
        ws.title = f'{year} SERVICEABLE'
        _fill_serviceable_sheet(ws, serviceable_items, supply_officer=supply_officer)
    elif SERVICEABLE_SHEET in wb.sheetnames:
        del wb[SERVICEABLE_SHEET]
    elif any(s.endswith('SERVICEABLE') for s in wb.sheetnames):
        for name in list(wb.sheetnames):
            if name.endswith('SERVICEABLE') and not include_serviceable:
                del wb[name]

    if include_unserviceable and UNSERVICEABLE_SHEET in wb.sheetnames:
        ws = wb[UNSERVICEABLE_SHEET]
        ws.title = f'{year} UNSERVICEABLE'
        _fill_unserviceable_sheet(ws, unserviceable_items, supply_officer=supply_officer)
    elif UNSERVICEABLE_SHEET in wb.sheetnames:
        del wb[UNSERVICEABLE_SHEET]

    if not wb.sheetnames:
        raise ValueError('No inventory sheets were generated for this report.')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    sheet_label = {
        'property_all': 'All_Property',
        'property_working': 'Serviceable',
        'property_unserviceable': 'Unserviceable',
        'property_disposed': 'Disposed',
    }.get(report_type, 'Inventory')

    filename = f'COA_Inventory_{sheet_label}_{len(equipment)}_items_{date.today()}.xlsx'
    return output, filename
