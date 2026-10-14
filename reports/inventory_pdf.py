"""COA inventory PDF export — mirrors the standard LGU inventory workbook layout."""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.models import SiteSettings
from reports.inventory_excel import (
    _article_description,
    _date_acquired,
    _group_equipment,
    _inventory_as_of_label,
    _inventory_year,
    _is_serviceable,
    _is_unserviceable,
    _municipality_line,
    _office_location,
    _province_line,
    _submitted_by,
    _total_cost,
    _unit_cost,
)

SERVICEABLE_COLUMN_COUNT = 9
UNSERVICEABLE_COLUMN_COUNT = 11


def _column_header_row(styles, *, unserviceable=False):
    """Two-line COA column headers — matches the Excel template layout."""
    header_style = ParagraphStyle(
        'InvColHeader',
        parent=styles['Normal'],
        fontSize=5,
        leading=6,
        alignment=1,
        textColor=colors.white,
        fontName='Helvetica-Bold',
    )
    hdr = lambda text: Paragraph(text.replace('\n', '<br/>'), header_style)
    if unserviceable:
        return [
            hdr('Qty.'), hdr('Unit'), hdr('Article\nDescription'), '', '',
            hdr('Class\nCode'), hdr('Date\nAcquired'), hdr('Property\nNumber'),
            hdr('Unit\nCost'), hdr('Total\nCost'), hdr('Office\nLocation'),
        ]
    return [
        hdr('Qty.'), hdr('Unit'), hdr('Article\nDescription'), hdr('Class\nCode'),
        hdr('Date\nAcquired'), hdr('Property\nNumber'), hdr('Unit\nCost'),
        hdr('Total\nCost'), hdr('Office\nLocation'),
    ]


def _fmt_cost(value):
    return f'{value:,.2f}'


def _fmt_date(value):
    return value.strftime('%d-%b-%y') if value else ''


def _inventory_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        'InvTitle',
        parent=styles['Heading2'],
        fontSize=11,
        alignment=1,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        'InvHeader',
        parent=styles['Normal'],
        fontSize=9,
        alignment=1,
        spaceAfter=2,
    ))
    return styles


def _header_elements(styles, *, title):
    site = SiteSettings.get_solo()
    return [
        Paragraph('Republic of the Philippines', styles['InvHeader']),
        Paragraph(_province_line(site), styles['InvHeader']),
        Paragraph(_municipality_line(site), styles['InvHeader']),
        Spacer(1, 0.2 * cm),
        Paragraph(title, styles['InvTitle']),
        Paragraph(_inventory_as_of_label(), styles['InvHeader']),
        Spacer(1, 0.3 * cm),
    ]


def _equipment_row(eq, *, unserviceable=False):
    qty = eq.quantity or 1
    unit_cost = _unit_cost(eq)
    total_cost = _total_cost(eq)
    desc = Paragraph(_article_description(eq), ParagraphStyle('d', fontSize=6, leading=7))
    row = [
        str(qty),
        (eq.unit or 'unit').strip(),
        desc,
        '',
        _fmt_date(_date_acquired(eq)),
        eq.property_number,
        _fmt_cost(unit_cost),
        _fmt_cost(total_cost),
        _office_location(eq),
    ]
    if unserviceable:
        row.insert(3, '')
        row.insert(4, '')
    return row


def _inventory_table_data(equipment_list, styles, *, unserviceable=False):
    col_count = UNSERVICEABLE_COLUMN_COUNT if unserviceable else SERVICEABLE_COLUMN_COUNT
    data = [_column_header_row(styles, unserviceable=unserviceable)]
    for subtotal_label, items in _group_equipment(equipment_list):
        for eq in items:
            data.append(_equipment_row(eq, unserviceable=unserviceable))
        group_total = sum(_total_cost(eq) for eq in items)
        label_span = col_count - 2
        subtotal_row = [subtotal_label] + [''] * (label_span - 1) + [_fmt_cost(group_total), '']
        data.append(subtotal_row)

    grand_total = sum(_total_cost(eq) for eq in equipment_list)
    label = (
        f"GRAND TOTAL OF {'UN' if unserviceable else ''}SERVICEABLE PPE's "
        f"as of DECEMBER 31, {_inventory_year()}"
    )
    label_span = col_count - 2
    data.append([label] + [''] * (label_span - 1) + [_fmt_cost(grand_total), ''])
    return data


def _table_style(col_count, *, unserviceable=False):
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A5F')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F7FA')]),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (-3, 1), (-2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 4),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('SPAN', (0, -1), (col_count - 3, -1)),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#8EAADB')),
    ])
    if unserviceable:
        style.add('SPAN', (2, 0), (4, 0))
    return style


def _signature_elements(styles, *, supply_officer=None):
    name, position = _submitted_by(SiteSettings.get_solo(), supply_officer=supply_officer)
    return [
        Spacer(1, 0.5 * cm),
        Paragraph('<b>Submitted by:</b>', styles['InvHeader']),
        Spacer(1, 0.6 * cm),
        Paragraph(f'<b>{name}</b>', styles['InvHeader']),
        Paragraph(position, styles['InvHeader']),
    ]


def _build_inventory_section(
    equipment_list, styles, *, title, unserviceable=False, supply_officer=None,
):
    if not equipment_list:
        return []
    elements = _header_elements(styles, title=title)
    table_data = _inventory_table_data(equipment_list, styles, unserviceable=unserviceable)
    col_widths = [0.7 * cm, 0.9 * cm, 3.6 * cm, 1.6 * cm, 1.5 * cm, 2.5 * cm, 1.7 * cm, 1.7 * cm, 3.0 * cm]
    if unserviceable:
        col_widths = [0.7 * cm, 0.9 * cm, 2.8 * cm, 0.4 * cm, 0.4 * cm, 1.6 * cm, 1.5 * cm, 2.4 * cm, 1.6 * cm, 1.6 * cm, 2.8 * cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(_table_style(len(col_widths), unserviceable=unserviceable))
    elements.append(table)
    elements.extend(_signature_elements(styles, supply_officer=supply_officer))
    return elements


def generate_inventory_pdf(
    equipment_list,
    report_type='property_all',
    supply_officer=None,
):
    """Build a COA inventory PDF using the same grouping rules as the Excel export."""
    equipment = list(equipment_list)
    if not equipment:
        raise ValueError('No equipment to export.')

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

    styles = _inventory_styles()
    elements = []
    if include_serviceable and serviceable_items:
        elements.extend(_build_inventory_section(
            serviceable_items,
            styles,
            title='INVENTORY OF SERVICEABLE PROPERTY, PLANT AND EQUIPMENT',
            supply_officer=supply_officer,
        ))
    if include_unserviceable and unserviceable_items:
        if elements:
            elements.append(PageBreak())
        elements.extend(_build_inventory_section(
            unserviceable_items,
            styles,
            title='INVENTORY OF UNSERVICEABLE PROPERTY, PLANT AND EQUIPMENT',
            unserviceable=True,
            supply_officer=supply_officer,
        ))
    if not elements:
        raise ValueError('No inventory sheets were generated for this report.')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1 * cm,
    )
    doc.build(elements)
    buffer.seek(0)

    sheet_label = {
        'property_all': 'All_Property',
        'property_working': 'Serviceable',
        'property_unserviceable': 'Unserviceable',
        'property_disposed': 'Disposed',
    }.get(report_type, 'Inventory')
    filename = f'COA_Inventory_{sheet_label}_{len(equipment)}_items_{date.today()}.pdf'
    return buffer, filename
