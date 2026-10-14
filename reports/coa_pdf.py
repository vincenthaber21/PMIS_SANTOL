"""COA form PDF generators — PAR, ICS, SPC, SPLC, RPCSP (Annex A)."""
import io
from datetime import date
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)

from core.models import SiteSettings
from core.signatories import (
    end_user_position,
    active_supply_officer_user,
    default_supply_officer_user,
    is_supply_officer,
    par_issued_by_position,
    resolve_par_received_by_user,
    resolve_supply_officer,
    supply_officer_position,
)
from equipment.coa import (
    LGU_NAME,
    effective_cost,
    get_rpcsp_data,
    get_semi_expendable_equipment,
    get_splc_transactions,
)
from equipment.spc import (
    get_spc_transactions,
    spc_fund_label,
    spc_lgu_name,
    spc_property_description,
    spc_semi_expendable_type,
    spc_useful_life_label,
)
from equipment.inventory_tag import _lgu_settings
from equipment.ics import ics_fund_cluster_display
from equipment.par import par_entity_name, par_fund_cluster_display
from .pdf_fonts import ensure_peso_font, peso_table_font_rules

HEADER_COLOR = colors.HexColor('#080')
ALT_ROW = colors.HexColor('#F0F4F8')


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='FormTitle', parent=styles['Title'], fontSize=14, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='FormSubtitle', parent=styles['Normal'], fontSize=10, textColor=colors.grey,
    ))
    return styles


def _header_block(styles, form_title, annex):
    return [
        Paragraph('REPUBLIC OF THE PHILIPPINES', styles['Normal']),
        Paragraph(LGU_NAME, styles['Heading3']),
        Paragraph('PROPERTY MANAGEMENT SYSTEM', styles['FormSubtitle']),
        Spacer(1, 0.3 * cm),
        Paragraph(form_title, styles['FormTitle']),
        Paragraph(f'Annex {annex} — COA Circular 3.1', styles['FormSubtitle']),
        Spacer(1, 0.4 * cm),
    ]


def _build_pdf(elements, filename_prefix):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm)
    doc.build(elements)
    buffer.seek(0)
    return buffer, f'{filename_prefix}_{date.today()}.pdf'


def _fmt_peso(amount):
    """Currency amounts with Philippine peso sign for SPC/SPLC/RPCSP PDF and Excel."""
    try:
        return f'₱{float(amount):,.2f}'
    except (TypeError, ValueError):
        return '₱0.00'


def _fmt_amount(amount):
    """ICS table amounts — no currency symbol, per COA Appendix 59."""
    try:
        return f'{float(amount):,.2f}'
    except (TypeError, ValueError):
        return '0.00'


def _manila_today():
    """Current calendar date in Asia/Manila."""
    return timezone.now().astimezone(ZoneInfo('Asia/Manila')).date()


def _user_office(user):
    """Position/office line for COA form signature blocks."""
    if not user:
        return ''
    if is_supply_officer(user):
        return supply_officer_position(user, include_department=True)
    return end_user_position(user)


def _par_styles():
    """Paragraph styles for PAR (Appendix 71)."""
    styles = _styles()
    styles.add(ParagraphStyle(
        name='ParAnnex',
        parent=styles['Normal'],
        fontSize=9,
        alignment=2,
        fontName='Helvetica-Oblique',
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name='ParHeaderTitle',
        parent=styles['Normal'],
        fontSize=12,
        leading=14,
        alignment=1,
        fontName='Helvetica-Bold',
        spaceBefore=2,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='ParLabel',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        alignment=0,
    ))
    styles.add(ParagraphStyle(
        name='ParLabelRight',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='ParSigHeader',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Helvetica-Bold',
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='ParSigNote',
        parent=styles['Normal'],
        fontSize=7,
        leading=9,
        alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='ParTableCell',
        parent=styles['Normal'],
        fontSize=7,
        leading=9,
        wordWrap='LTR',
    ))
    styles.add(ParagraphStyle(
        name='ParFooter',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        fontName='Helvetica-Oblique',
    ))
    styles.add(ParagraphStyle(
        name='ParSigDate',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        alignment=0,
    ))
    styles.add(ParagraphStyle(
        name='ParSigValue',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        alignment=1,
        fontName='Helvetica-Bold',
        underlineProportion=0.12,
        underlineOffset=-2,
        underlineWidth=0.5,
    ))
    return styles


PAR_MARGIN_TOP = 1.2 * cm
PAR_MARGIN_BOTTOM = 1.2 * cm
PAR_MARGIN_H = 1.5 * cm
PAR_DATA_ROW_HEIGHT = 18
PAR_TABLE_HEADER_HEIGHT = 22
PAR_HEADER_BLOCK_HEIGHT = 72
PAR_SIG_BLOCK_HEIGHT = 133
PAR_FOOTER_BLOCK_HEIGHT = 35
PAR_MIN_BLANK_ROWS = 2


def _par_usable_dimensions():
    """Usable width and height inside PAR page margins."""
    page_w, page_h = A4
    return (
        page_w - 2 * PAR_MARGIN_H,
        page_h - PAR_MARGIN_TOP - PAR_MARGIN_BOTTOM,
    )


def _par_compute_body_fill(item_count, usable_h):
    """
    Blank rows and row height so the item grid fills one A4 page before signatures.
    Returns (blank_row_count, blank_row_height).
    """
    fixed = (
        PAR_HEADER_BLOCK_HEIGHT + PAR_TABLE_HEADER_HEIGHT
        + PAR_SIG_BLOCK_HEIGHT + PAR_FOOTER_BLOCK_HEIGHT
    )
    available = usable_h - fixed - item_count * PAR_DATA_ROW_HEIGHT
    if available < PAR_DATA_ROW_HEIGHT:
        return (1, PAR_DATA_ROW_HEIGHT) if available >= PAR_DATA_ROW_HEIGHT * 0.5 else (0, PAR_DATA_ROW_HEIGHT)

    blank_rows = max(PAR_MIN_BLANK_ROWS, int(available // PAR_DATA_ROW_HEIGHT))
    blank_row_height = available / blank_rows
    return blank_rows, blank_row_height


def _par_item_col_widths(usable_w, line_items=None):
    """Appendix 71 PAR body — column widths; property number grows with content."""
    ratios = [0.75, 0.75, 2.4, 1.4, 1.1, 1.0]
    if line_items:
        max_prop = max(
            (len(str(getattr(item, 'property_number', '') or '')) for item in line_items),
            default=0,
        )
        if max_prop > 16:
            extra = min((max_prop - 16) * 0.065, 1.0)
            ratios[3] += extra
            ratios[2] = max(1.5, ratios[2] - extra * 0.6)
    scale = usable_w / sum(ratios)
    return [r * scale for r in ratios]


def _par_property_number_paragraph(prop_no, styles):
    """Property number cell — wraps long values inside the column."""
    text = escape(prop_no or '')
    if len(prop_no or '') > 22:
        return Paragraph(f'<font size="6">{text}</font>', styles['ParTableCell'])
    return Paragraph(text, styles['ParTableCell'])


def _par_item_table_style(item_count, blank_row_count, blank_row_height):
    """6-column PAR item grid — signatures attach in a separate 50/50 table below."""
    border = 0.75
    blank_start = 1 + item_count
    blank_end = blank_start + blank_row_count - 1
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('ALIGN', (2, 1), (2, -1), 'LEFT'),
        ('ALIGN', (3, 1), (3, -1), 'CENTER'),
        ('ALIGN', (4, 1), (4, -1), 'CENTER'),
        ('ALIGN', (5, 1), (5, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('VALIGN', (0, 1), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), border, colors.black),
        ('GRID', (0, 0), (-1, -1), border, colors.black),
        ('MINHEIGHT', (0, 1), (-1, item_count), PAR_DATA_ROW_HEIGHT),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (2, 1), (2, -1), 4),
        ('RIGHTPADDING', (5, 1), (5, -1), 4),
    ]
    if blank_row_count > 0 and blank_end >= blank_start:
        style_cmds.append(
            ('MINHEIGHT', (0, blank_start), (-1, blank_end), blank_row_height),
        )
    return TableStyle(style_cmds)


def _par_sig_date_display(value):
    """PAR signature date — e.g. JULY 6, 2026."""
    if value is None or value == '':
        return ''
    if isinstance(value, str):
        from django.utils.dateparse import parse_date
        parsed = parse_date(value)
        if parsed:
            value = parsed
        else:
            return value.upper()
    if hasattr(value, 'day') and hasattr(value, 'strftime'):
        return f'{value.strftime("%B").upper()} {value.day}, {value.year}'
    return str(value).upper()


def _par_sig_table_style(last_row):
    """Signature block — equal 50/50 columns, shares top border with item table."""
    border = 0.75
    return TableStyle([
        ('FONTSIZE', (0, 0), (-1, last_row), 8),
        ('ALIGN', (0, 0), (1, 0), 'LEFT'),
        ('ALIGN', (0, 1), (-1, last_row), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBEFORE', (0, 0), (0, last_row), border, colors.black),
        ('LINEAFTER', (-1, 0), (-1, last_row), border, colors.black),
        ('LINEBELOW', (0, last_row), (-1, last_row), border, colors.black),
        ('LINEBEFORE', (1, 0), (1, last_row), border, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('MINHEIGHT', (0, 1), (-1, 1), 22),
        ('MINHEIGHT', (0, 2), (-1, 2), 16),
        ('MINHEIGHT', (0, 3), (-1, 3), 14),
        ('MINHEIGHT', (0, 5), (-1, 5), 14),
    ])


def _par_sig_row(left, right):
    """One signature row in the 2-column signature table."""
    return [left, right]


def _par_item_display_description(item):
    """PAR description column — plain item description (Appendix 71)."""
    return (item.description or '').strip()


def _par_signatories(
    site, par=None, supply_officer=None, end_user=None, signatory_overrides=None,
    *, blank_received_by=False,
):
    """Resolve PAR signature block names and positions."""
    issued_by_position = par_issued_by_position()
    if blank_received_by:
        end_user = None
    else:
        end_user = resolve_par_received_by_user(par=par, end_user=end_user)
    supply_officer = (
        active_supply_officer_user(user=supply_officer)
        or default_supply_officer_user()
    )
    issued_by_name = (
        supply_officer.get_full_name() if supply_officer else ''
    ) or (supply_officer.username if supply_officer else '')
    if signatory_overrides:
        by_name = signatory_overrides.get('received_by_name', '')
        by_position = signatory_overrides.get('received_by_position', '')
        if not blank_received_by:
            if not by_name and end_user:
                by_name = end_user.get_full_name() or end_user.username
            if not by_position and end_user:
                by_position = end_user_position(end_user)
        return {
            'by_name': by_name,
            'by_position': by_position,
            'from_name': issued_by_name,
            'from_position': issued_by_position,
        }
    if site.par_use_site_signatories and not blank_received_by:
        return {
            'by_name': (
                site.par_received_by_name
                or (end_user.get_full_name() if end_user else '')
            ),
            'from_name': site.par_received_from_name or issued_by_name,
            'by_position': (
                site.par_received_by_position
                or end_user_position(end_user)
            ),
            'from_position': issued_by_position,
        }
    return {
        'by_name': '' if blank_received_by else (end_user.get_full_name() if end_user else ''),
        'from_name': issued_by_name,
        'by_position': '' if blank_received_by else end_user_position(end_user),
        'from_position': issued_by_position,
    }


def _par_header_elements(site, styles, usable_w, *, par_no='', entity_name='', fund_cluster=''):
    """Appendix 71 label + bordered title / entity / fund / PAR no. block."""
    left_w = usable_w * 0.62
    right_w = usable_w * 0.38
    elements = [
        Paragraph('<i>Appendix 71</i>', styles['ParAnnex']),
        Spacer(1, 0.05 * cm),
    ]
    header_data = [
        [Paragraph(escape(site.par_header_title.upper()), styles['ParHeaderTitle']), ''],
        [Paragraph(f'<b>Entity Name:</b> {escape(entity_name)}', styles['ParLabel']), ''],
        [
            Paragraph(f'<b>Fund Cluster:</b> {escape(fund_cluster)}', styles['ParLabel']),
            Paragraph(f'<b>PAR No.:</b> {escape(par_no)}', styles['ParLabelRight']),
        ],
    ]
    header_table = Table(header_data, colWidths=[left_w, right_w])
    header_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('SPAN', (0, 0), (1, 0)),
        ('SPAN', (0, 1), (1, 1)),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 2), (1, 2), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(header_table)
    return elements


def _par_item_table_elements(line_items, styles, usable_w, usable_h):
    """Item grid with auto-sized blank rows to fill the page above signatures."""
    col_widths = _par_item_col_widths(usable_w, line_items)
    item_count = len(line_items)
    blank_rows, blank_row_height = _par_compute_body_fill(item_count, usable_h)

    item_data = [[
        'Quantity', 'Unit', 'Description', 'Property Number', 'Date Acquired', 'Amount',
    ]]
    for item in line_items:
        item_data.append([
            str(item.quantity),
            item.unit,
            Paragraph(escape(_par_item_display_description(item)), styles['ParTableCell']),
            _par_property_number_paragraph(item.property_number, styles),
            str(item.date_acquired or ''),
            _fmt_amount(item.amount),
        ])

    blank_cell = '\u00a0'
    for _ in range(blank_rows):
        item_data.append([blank_cell] * 6)

    item_table = Table(item_data, colWidths=col_widths, repeatRows=1)
    item_table.setStyle(_par_item_table_style(item_count, blank_rows, blank_row_height))
    layout = {
        'item_count': item_count,
        'blank_rows': blank_rows,
        'blank_row_height': blank_row_height,
    }
    return [item_table], layout


def _par_signature_elements(signatories, styles, half_w, sig_date_by, sig_date_from=None):
    """Received by / Issued by — COA Appendix 71 standard signature block."""
    if sig_date_from is None:
        sig_date_from = sig_date_by
    sig_name = lambda n: Paragraph(
        f'<u>{escape((n or "").upper())}</u>', styles['ParSigValue'],
    )
    sig_pos = lambda p: Paragraph(
        f'<u>{escape((p or "").upper())}</u>', styles['ParSigValue'],
    )
    sig_date = lambda d: Paragraph(
        f'<u>{escape(_par_sig_date_display(d))}</u>', styles['ParSigValue'],
    )
    sig_data = [
        _par_sig_row(
            Paragraph('Received by:', styles['ParSigHeader']),
            Paragraph('Issued by:', styles['ParSigHeader']),
        ),
        _par_sig_row(sig_name(signatories['by_name']), sig_name(signatories['from_name'])),
        _par_sig_row(
            Paragraph('Signature over Printed Name of End User', styles['ParSigNote']),
            Paragraph(
                'Signature over Printed Name of Supply and/or Property Custodian',
                styles['ParSigNote'],
            ),
        ),
        _par_sig_row(
            sig_pos(signatories['by_position']),
            sig_pos(signatories['from_position']),
        ),
        _par_sig_row(
            Paragraph('Position/Office', styles['ParSigNote']),
            Paragraph('Position/Office', styles['ParSigNote']),
        ),
        _par_sig_row(sig_date(sig_date_by), sig_date(sig_date_from)),
        _par_sig_row(
            Paragraph('Date', styles['ParSigNote']),
            Paragraph('Date', styles['ParSigNote']),
        ),
    ]
    sig_table = Table(sig_data, colWidths=[half_w, half_w])
    sig_table.setStyle(_par_sig_table_style(len(sig_data) - 1))
    return [sig_table]


def _par_body_table_elements(line_items, signatories, styles, usable_w, usable_h, sig_date_by, sig_date_from=None):
    """Item grid + signature block as separate tables for correct 50/50 layout."""
    half_w = usable_w / 2
    item_elements, layout = _par_item_table_elements(line_items, styles, usable_w, usable_h)
    sig_elements = _par_signature_elements(
        signatories, styles, half_w, sig_date_by, sig_date_from=sig_date_from,
    )
    return item_elements + sig_elements, layout


def _par_estimated_content_height(item_count, blank_rows, blank_row_height):
    """Approximate flowable height above the page footer."""
    return (
        PAR_HEADER_BLOCK_HEIGHT + PAR_TABLE_HEADER_HEIGHT
        + item_count * PAR_DATA_ROW_HEIGHT
        + blank_rows * blank_row_height
        + PAR_SIG_BLOCK_HEIGHT
    )


def _par_footer_elements(
    site, styles, half_w, usable_h=None, content_height=None,
    page_num=1, page_total=1,
):
    """Footer title and page number, pinned near the bottom when space allows."""
    elements = []
    if usable_h is not None and content_height is not None:
        gap = usable_h - content_height - PAR_FOOTER_BLOCK_HEIGHT
        if gap > 4:
            elements.append(Spacer(1, gap))
    elements.append(Spacer(1, 0.2 * cm))
    page_label = f'Page {page_num}/{page_total}'
    footer = Table(
        [[
            Paragraph(site.par_header_title.title(), styles['ParFooter']),
            Paragraph(page_label, styles['ParFooter']),
        ]],
        colWidths=[half_w, half_w],
    )
    footer.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(footer)
    return elements


def _build_par_card_elements(par, styles, supply_officer=None, end_user=None, signatory_overrides=None):
    """Flowables for one PAR — COA Appendix 71 layout."""
    usable_w, usable_h = _par_usable_dimensions()
    half_w = usable_w / 2
    site = SiteSettings.get_solo()
    sig_date_by = str(par.date_received)
    sig_date_from = str(par.date_issued)
    signatories = _par_signatories(
        site, par,
        supply_officer=supply_officer,
        end_user=end_user,
        signatory_overrides=signatory_overrides,
    )
    line_items = list(par.items.all())

    elements = []
    elements.extend(_par_header_elements(
        site, styles, usable_w,
        par_no=par.par_no,
        entity_name=par_entity_name(par=par),
        fund_cluster=par_fund_cluster_display(par=par),
    ))
    body_elements, layout = _par_body_table_elements(
        line_items, signatories, styles, usable_w, usable_h,
        sig_date_by, sig_date_from=sig_date_from,
    )
    elements.extend(body_elements)
    content_height = _par_estimated_content_height(
        layout['item_count'], layout['blank_rows'], layout['blank_row_height'],
    )
    elements.extend(_par_footer_elements(
        site, styles, half_w, usable_h=usable_h, content_height=content_height,
    ))
    return elements


def _par_max_items_per_page():
    """Approximate item rows that fit on one PAR page with minimum blank rows."""
    _, usable_h = _par_usable_dimensions()
    fixed = (
        PAR_HEADER_BLOCK_HEIGHT + PAR_TABLE_HEADER_HEIGHT
        + PAR_SIG_BLOCK_HEIGHT + PAR_FOOTER_BLOCK_HEIGHT
    )
    reserved_blank = PAR_MIN_BLANK_ROWS * PAR_DATA_ROW_HEIGHT
    return max(1, int((usable_h - fixed - reserved_blank) // PAR_DATA_ROW_HEIGHT))


def _par_line_items_from_equipment(equipment_list):
    """Build PAR table rows from equipment (all property report items)."""
    from equipment.coa import effective_cost
    from equipment.par import _equipment_description, _equipment_unit

    line_items = []
    for equipment in equipment_list:
        line_items.append(type('ParLineItem', (), {
            'quantity': 1,
            'unit': _equipment_unit(equipment),
            'description': _equipment_description(equipment),
            'property_number': equipment.property_number,
            'date_acquired': equipment.purchase_date,
            'amount': effective_cost(equipment),
        })())
    return line_items


def _par_group_key(par):
    """Grouping key — entity name, fund cluster, and received-by end user."""
    return (
        par_entity_name(par=par),
        par_fund_cluster_display(par=par),
        par.end_user_id,
    )


def _group_pars_by_receipt(par_list):
    """Group PAR records with the same entity, fund cluster, and received-by."""
    groups = []
    index_by_key = {}
    for par in par_list:
        key = _par_group_key(par)
        if key in index_by_key:
            groups[index_by_key[key]].append(par)
        else:
            index_by_key[key] = len(groups)
            groups.append([par])
    return groups


def _par_line_items_from_group(par_group):
    """Collect line items from a group of PAR records in order."""
    line_items = []
    for par in par_group:
        line_items.extend(par.items.all())
    return line_items


def _par_numbers_for_group(par_group):
    """Comma-separated PAR control numbers for a grouped form."""
    return ', '.join(par.par_no for par in par_group)


def _build_par_combined_elements(
    line_items,
    styles,
    supply_officer=None,
    end_user=None,
    page_num=1,
    page_total=1,
    signatory_overrides=None,
    *,
    par_no='',
    entity_name='',
    fund_cluster='',
    blank_received_by=False,
    par=None,
    sig_date_by=None,
    sig_date_from=None,
):
    """One PAR form — all line items listed as rows in a single item table."""
    usable_w, usable_h = _par_usable_dimensions()
    half_w = usable_w / 2
    site = SiteSettings.get_solo()
    if sig_date_by is None:
        sig_date_by = str(par.date_received) if par else str(_manila_today())
    if sig_date_from is None:
        sig_date_from = str(par.date_issued) if par else sig_date_by
    signatories = _par_signatories(
        site,
        par=par,
        supply_officer=supply_officer,
        end_user=end_user,
        signatory_overrides=signatory_overrides,
        blank_received_by=blank_received_by,
    )

    elements = []
    elements.extend(_par_header_elements(
        site, styles, usable_w,
        par_no=par_no,
        entity_name=entity_name,
        fund_cluster=fund_cluster,
    ))
    body_elements, layout = _par_body_table_elements(
        line_items, signatories, styles, usable_w, usable_h,
        sig_date_by, sig_date_from=sig_date_from,
    )
    elements.extend(body_elements)
    content_height = _par_estimated_content_height(
        layout['item_count'], layout['blank_rows'], layout['blank_row_height'],
    )
    elements.extend(_par_footer_elements(
        site, styles, half_w, usable_h=usable_h, content_height=content_height,
        page_num=page_num, page_total=page_total,
    ))
    return elements


def _build_par_combined_from_pars(
    par_list, styles, supply_officer=None, end_user=None, signatory_overrides=None,
):
    """Render each PAR record as its own Appendix 71 form."""
    elements = []
    for idx, par in enumerate(par_list):
        if idx > 0:
            elements.append(PageBreak())
        elements.extend(_build_par_card_elements(
            par, styles,
            supply_officer=supply_officer,
            end_user=end_user,
            signatory_overrides=signatory_overrides,
        ))
    return elements


def _build_par_combined_pages(
    line_items, styles, supply_officer=None, end_user=None, signatory_overrides=None,
    *, equipment_list=None, par_no='', entity_name=None, fund_cluster=None,
    blank_received_by=False,
):
    """Paginate line items across PAR pages when they exceed one sheet."""
    if not entity_name:
        entity_name = par_entity_name(equipment_list=equipment_list, end_user=end_user)
    if not fund_cluster:
        fund_cluster = par_fund_cluster_display(equipment_list=equipment_list)
    per_page = _par_max_items_per_page()
    chunks = [
        line_items[i:i + per_page]
        for i in range(0, len(line_items), per_page)
    ] or [[]]
    page_total = len(chunks)
    elements = []
    for idx, chunk in enumerate(chunks, start=1):
        if idx > 1:
            elements.append(PageBreak())
        elements.extend(_build_par_combined_elements(
            chunk,
            styles,
            supply_officer=supply_officer,
            end_user=end_user,
            page_num=idx,
            page_total=page_total,
            signatory_overrides=signatory_overrides,
            par_no=par_no,
            entity_name=entity_name,
            fund_cluster=fund_cluster,
            blank_received_by=blank_received_by,
        ))
    return elements


def generate_par_pdf(par, supply_officer=None, end_user=None, signatory_overrides=None):
    """Property Acknowledgment Receipt (Appendix 71) — single-page layout."""
    styles = _par_styles()
    items = list(par.items.all())

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    doc.build(_build_par_card_elements(
        par, styles,
        supply_officer=supply_officer,
        end_user=end_user,
        signatory_overrides=signatory_overrides,
    ))
    buffer.seek(0)
    prop_no = items[0].property_number if items else 'PAR'
    return buffer, f'PAR_{par.par_no}_{prop_no}.pdf'


def generate_all_par_pdf(par_list, supply_officer=None, end_user=None, signatory_overrides=None):
    """All PAR records in one PDF — same entity, fund cluster, and received-by combined."""
    items = list(par_list)
    if not items:
        raise ValueError('No PAR records to export.')

    styles = _par_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    elements = []
    first_page = True
    per_page = _par_max_items_per_page()
    for group in _group_pars_by_receipt(items):
        primary = group[0]
        all_line_items = _par_line_items_from_group(group)
        par_no = _par_numbers_for_group(group) if len(group) > 1 else primary.par_no
        entity_name = par_entity_name(par=primary)
        fund_cluster = par_fund_cluster_display(par=primary)
        group_end_user = end_user or primary.end_user
        chunks = [
            all_line_items[i:i + per_page]
            for i in range(0, len(all_line_items), per_page)
        ] or [[]]
        page_total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            if not first_page:
                elements.append(PageBreak())
            first_page = False
            elements.extend(_build_par_combined_elements(
                chunk,
                styles,
                supply_officer=supply_officer,
                end_user=group_end_user,
                page_num=idx,
                page_total=page_total,
                signatory_overrides=signatory_overrides,
                par_no=par_no,
                entity_name=entity_name,
                fund_cluster=fund_cluster,
                par=primary,
                sig_date_by=str(primary.date_received),
                sig_date_from=str(primary.date_issued),
            ))

    doc.build(elements)
    buffer.seek(0)
    item_count = sum(par.items.count() for par in items)
    return buffer, f'PAR_All_{item_count}_items_{date.today()}.pdf'


def generate_par_pdf_from_equipment(
    equipment_list, supply_officer=None, end_user=None, signatory_overrides=None,
    *, entity_name=None, fund_cluster=None, blank_received_by=False,
):
    """Property report export — PAR format (Appendix 71) for all filtered equipment rows."""
    equipment = list(equipment_list)
    if not equipment:
        raise ValueError('No equipment to export.')

    from equipment.par import get_active_par_for_equipment

    par_no = ''
    for eq in equipment:
        active_par = get_active_par_for_equipment(eq)
        if active_par:
            par_no = active_par.par_no
            break

    if not entity_name:
        entity_name = par_entity_name(equipment_list=equipment, end_user=end_user)
    if not fund_cluster:
        fund_cluster = par_fund_cluster_display(equipment_list=equipment)

    line_items = _par_line_items_from_equipment(equipment)
    styles = _par_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    doc.build(_build_par_combined_pages(
        line_items,
        styles,
        supply_officer=supply_officer,
        end_user=end_user,
        signatory_overrides=signatory_overrides,
        equipment_list=equipment,
        par_no=par_no,
        entity_name=entity_name,
        fund_cluster=fund_cluster,
        blank_received_by=blank_received_by,
    ))
    buffer.seek(0)
    return buffer, f'PAR_Report_{len(equipment)}_items_{date.today()}.pdf'


def generate_par_pdf_from_event(event):
    """Backward-compatible wrapper when only an issuance event dict is available."""
    from equipment.models import PropertyAcknowledgmentReceipt
    par = PropertyAcknowledgmentReceipt.objects.filter(
        reference_type=event.get('reference_type', ''),
        reference_id=event.get('reference_id'),
    ).first()
    if par:
        return generate_par_pdf(par)
    raise ValueError('No PAR record found for this issuance event.')


def generate_ics_pdf(ics):
    """Inventory Custodian Slip (COA Circular 2022-004 Appendix 59)."""
    styles = _ics_styles()
    items = list(ics.items.all())

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    doc.build(_build_ics_card_elements(ics, styles))
    buffer.seek(0)
    prop_no = items[0].inventory_item_no if items else 'ICS'
    return buffer, f'ICS_{ics.ics_no}_{prop_no}.pdf'


def generate_ics_pdf_from_event(event):
    """Backward-compatible wrapper when only an issuance event dict is available."""
    from equipment.models import InventoryCustodianSlip
    ics = InventoryCustodianSlip.objects.filter(
        reference_type=event.get('reference_type', ''),
        reference_id=event.get('reference_id'),
    ).prefetch_related('items').first()
    if ics:
        return generate_ics_pdf(ics)
    raise ValueError('No ICS record found for this issuance event.')


ICS_MARGIN_TOP = PAR_MARGIN_TOP
ICS_MARGIN_BOTTOM = PAR_MARGIN_BOTTOM
ICS_MARGIN_H = PAR_MARGIN_H
ICS_DATA_ROW_HEIGHT = PAR_DATA_ROW_HEIGHT
ICS_TABLE_HEADER_HEIGHT = 36
ICS_HEADER_BLOCK_HEIGHT = 168
ICS_SIG_BLOCK_HEIGHT = PAR_SIG_BLOCK_HEIGHT
ICS_FOOTER_BLOCK_HEIGHT = PAR_FOOTER_BLOCK_HEIGHT
ICS_MIN_BLANK_ROWS = PAR_MIN_BLANK_ROWS


def _ics_usable_dimensions():
    """Usable width and height inside ICS page margins."""
    page_w, page_h = A4
    return (
        page_w - 2 * ICS_MARGIN_H,
        page_h - ICS_MARGIN_TOP - ICS_MARGIN_BOTTOM,
    )


def _ics_compute_body_fill(item_count, usable_h):
    """Blank rows and row height so the ICS item grid fills the page above signatures."""
    fixed = (
        ICS_HEADER_BLOCK_HEIGHT + ICS_TABLE_HEADER_HEIGHT
        + ICS_SIG_BLOCK_HEIGHT + ICS_FOOTER_BLOCK_HEIGHT
    )
    available = usable_h - fixed - item_count * ICS_DATA_ROW_HEIGHT
    if available < ICS_DATA_ROW_HEIGHT:
        return (1, ICS_DATA_ROW_HEIGHT) if available >= ICS_DATA_ROW_HEIGHT * 0.5 else (0, ICS_DATA_ROW_HEIGHT)

    blank_rows = max(ICS_MIN_BLANK_ROWS, int(available // ICS_DATA_ROW_HEIGHT))
    blank_row_height = available / blank_rows
    return blank_rows, blank_row_height


def _ics_max_items_per_page():
    """Approximate item rows that fit on one ICS page with minimum blank rows."""
    _, usable_h = _ics_usable_dimensions()
    fixed = (
        ICS_HEADER_BLOCK_HEIGHT + ICS_TABLE_HEADER_HEIGHT
        + ICS_SIG_BLOCK_HEIGHT + ICS_FOOTER_BLOCK_HEIGHT
    )
    reserved_blank = ICS_MIN_BLANK_ROWS * ICS_DATA_ROW_HEIGHT
    return max(1, int((usable_h - fixed - reserved_blank) // ICS_DATA_ROW_HEIGHT))


def _group_ics_by_entity(ics_list):
    """Group ICS records that share the same entity name."""
    groups = []
    index_by_entity = {}
    for ics in ics_list:
        key = (ics.entity_name or '').strip()
        if key in index_by_entity:
            groups[index_by_entity[key]].append(ics)
        else:
            index_by_entity[key] = len(groups)
            groups.append([ics])
    return groups


def _ics_line_items_from_group(ics_group):
    """Collect line items from a group of ICS records in order."""
    line_items = []
    for ics in ics_group:
        line_items.extend(ics.items.all())
    return line_items


def _ics_fund_cluster_for_group(ics_group):
    """Fund cluster label for a grouped ICS — shared value or first slip."""
    labels = [ics_fund_cluster_display(ics) for ics in ics_group]
    unique = []
    for label in labels:
        if label not in unique:
            unique.append(label)
    if len(unique) == 1:
        return unique[0]
    return labels[0]


def _ics_numbers_for_group(ics_group):
    """Comma-separated ICS control numbers for a grouped form."""
    return ', '.join(ics.ics_no for ics in ics_group)


def generate_all_ics_pdf(ics_list):
    """All ICS forms in one PDF — same entity name combined on one page."""
    items = list(ics_list)
    if not items:
        raise ValueError('No ICS records to export.')

    styles = _ics_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    elements = []
    first_page = True
    per_page = _ics_max_items_per_page()
    for group in _group_ics_by_entity(items):
        all_line_items = _ics_line_items_from_group(group)
        chunks = [
            all_line_items[i:i + per_page]
            for i in range(0, len(all_line_items), per_page)
        ] or [[]]
        page_total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            if not first_page:
                elements.append(PageBreak())
            first_page = False
            elements.extend(_build_ics_group_elements(
                group,
                styles,
                line_items=chunk,
                page_num=idx,
                page_total=page_total,
            ))

    doc.build(elements)
    buffer.seek(0)
    return buffer, f'ICS_All_{len(items)}_records_{date.today()}.pdf'


def _ics_styles():
    """Paragraph styles for ICS (Appendix 59)."""
    styles = _styles()
    styles.add(ParagraphStyle(
        name='IcsTitle',
        parent=styles['Normal'],
        fontSize=12,
        leading=14,
        alignment=1,
        spaceAfter=8,
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        name='IcsLabel',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
    ))
    styles.add(ParagraphStyle(
        name='IcsAnnex',
        parent=styles['Normal'],
        fontSize=9,
        alignment=2,
        fontName='Helvetica-Oblique',
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name='IcsLabelRight',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='IcsHeaderTitle',
        parent=styles['Normal'],
        fontSize=12,
        leading=14,
        alignment=1,
        fontName='Helvetica-Bold',
        spaceBefore=2,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='IcsSigHeader',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Helvetica-Bold',
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name='IcsSigNote',
        parent=styles['Normal'],
        fontSize=7,
        leading=9,
        alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='IcsTableCell',
        parent=styles['Normal'],
        fontSize=7,
        leading=9,
        wordWrap='LTR',
    ))
    styles.add(ParagraphStyle(
        name='IcsFooter',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        fontName='Helvetica-Oblique',
    ))
    styles.add(ParagraphStyle(
        name='IcsSigValue',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        alignment=1,
        fontName='Helvetica-Bold',
        underlineProportion=0.12,
        underlineOffset=-2,
        underlineWidth=0.5,
    ))
    return styles


def _ics_item_col_widths(usable_w, line_items=None):
    """Eight columns — left half (qty/unit/desc) and right half for amount/inventory."""
    half = usable_w / 2
    left_ratios = [0.9, 1.0, 2.5, 2.5]
    right_ratios = [2.0, 2.0, 3.8, 1.1]
    if line_items:
        max_inv = max(
            (len(str(getattr(item, 'inventory_item_no', '') or '')) for item in line_items),
            default=0,
        )
        if max_inv > 18:
            extra = min((max_inv - 18) * 0.06, 0.9)
            right_ratios[2] += extra
            left_ratios[2] = max(1.8, left_ratios[2] - extra * 0.4)
            left_ratios[3] = max(1.8, left_ratios[3] - extra * 0.4)
    left_scale = half / sum(left_ratios)
    right_scale = half / sum(right_ratios)
    return [r * left_scale for r in left_ratios] + [r * right_scale for r in right_ratios]


def _ics_inventory_no_paragraph(inv_no, styles):
    """Inventory item number cell — wraps long values inside the column."""
    text = escape(inv_no or '')
    if len(inv_no or '') > 22:
        return Paragraph(f'<font size="6">{text}</font>', styles['IcsTableCell'])
    return Paragraph(text, styles['IcsTableCell'])


def _ics_item_table_style(item_count, blank_row_count, blank_row_height):
    """8-column ICS item grid — two-row header, signatures attach in a separate table below."""
    border = 0.75
    blank_start = 2 + item_count
    blank_end = blank_start + blank_row_count - 1
    desc_end_row = 1 + item_count
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
        ('ALIGN', (0, 2), (1, -1), 'CENTER'),
        ('ALIGN', (2, 2), (3, -1), 'LEFT'),
        ('ALIGN', (4, 2), (5, -1), 'RIGHT'),
        ('ALIGN', (6, 2), (6, -1), 'CENTER'),
        ('ALIGN', (7, 2), (7, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 1), 'MIDDLE'),
        ('VALIGN', (0, 2), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), border, colors.black),
        ('GRID', (0, 0), (-1, -1), border, colors.black),
        ('MINHEIGHT', (0, 2), (-1, 1 + item_count), ICS_DATA_ROW_HEIGHT),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (2, 2), (3, -1), 4),
        ('RIGHTPADDING', (4, 2), (5, -1), 4),
        ('SPAN', (2, 0), (3, 0)),
        ('SPAN', (4, 0), (5, 0)),
        ('SPAN', (2, 1), (3, 1)),
    ] + [
        ('SPAN', (2, row), (3, row)) for row in range(2, desc_end_row + 1)
    ]
    if blank_row_count > 0 and blank_end >= blank_start:
        style_cmds.append(
            ('MINHEIGHT', (0, blank_start), (-1, blank_end), blank_row_height),
        )
        style_cmds.extend([
            ('SPAN', (2, row), (3, row)) for row in range(blank_start, blank_end + 1)
        ])
    return TableStyle(style_cmds)


def _ics_item_table_elements(line_items, styles, usable_w, usable_h):
    """ICS item grid with auto-sized blank rows to fill the page above signatures."""
    col_widths = _ics_item_col_widths(usable_w, line_items)
    item_count = len(line_items)
    blank_rows, blank_row_height = _ics_compute_body_fill(item_count, usable_h)

    item_data = [
        ['Qty.', 'Unit', 'Description', '', 'Amount', '', 'Inventory Item No.', 'Estimated\nUseful Life'],
        ['', '', '', '', 'Unit Cost', 'Total Cost', '', ''],
    ]
    for item in line_items:
        item_data.append([
            str(item.quantity),
            item.unit,
            Paragraph(escape(item.description or ''), styles['IcsTableCell']),
            '',
            _fmt_amount(item.estimated_unit_cost),
            _fmt_amount(item.total_cost),
            _ics_inventory_no_paragraph(item.inventory_item_no, styles),
            str(item.useful_life),
        ])

    blank_cell = '\u00a0'
    for _ in range(blank_rows):
        item_data.append([blank_cell, blank_cell, blank_cell, blank_cell, '', '', '', ''])

    item_table = Table(item_data, colWidths=col_widths, repeatRows=2)
    item_table.setStyle(_ics_item_table_style(item_count, blank_rows, blank_row_height))
    layout = {
        'item_count': item_count,
        'blank_rows': blank_rows,
        'blank_row_height': blank_row_height,
    }
    return [item_table], layout


def _ics_signature_elements(signatories, styles, half_w, sig_date_by, sig_date_from=None):
    """Received by / Received from — PAR-style signature block for ICS."""
    if sig_date_from is None:
        sig_date_from = sig_date_by
    sig_name = lambda n: Paragraph(
        f'<u>{escape((n or "").upper())}</u>', styles['IcsSigValue'],
    )
    sig_pos = lambda p: Paragraph(
        f'<u>{escape((p or "").upper())}</u>', styles['IcsSigValue'],
    )
    sig_date = lambda d: Paragraph(
        f'<u>{escape(_par_sig_date_display(d))}</u>', styles['IcsSigValue'],
    )
    sig_data = [
        [
            Paragraph('Received by:', styles['IcsSigHeader']),
            Paragraph('Received from:', styles['IcsSigHeader']),
        ],
        [sig_name(signatories['by_name']), sig_name(signatories['from_name'])],
        [
            Paragraph('Signature Over Printed Name', styles['IcsSigNote']),
            Paragraph('Signature Over Printed Name', styles['IcsSigNote']),
        ],
        [sig_pos(signatories['by_position']), sig_pos(signatories['from_position'])],
        [
            Paragraph('Position/Office', styles['IcsSigNote']),
            Paragraph('Position/Office', styles['IcsSigNote']),
        ],
        [sig_date(sig_date_by), sig_date(sig_date_from)],
        [
            Paragraph('Date', styles['IcsSigNote']),
            Paragraph('Date', styles['IcsSigNote']),
        ],
    ]
    sig_table = Table(sig_data, colWidths=[half_w, half_w])
    sig_table.setStyle(_par_sig_table_style(len(sig_data) - 1))
    return [sig_table]


def _ics_body_table_elements(line_items, signatories, styles, usable_w, usable_h, sig_date_by, sig_date_from=None):
    """Item grid + signature block as separate tables for correct 50/50 layout."""
    half_w = usable_w / 2
    item_elements, layout = _ics_item_table_elements(line_items, styles, usable_w, usable_h)
    sig_elements = _ics_signature_elements(
        signatories, styles, half_w, sig_date_by, sig_date_from=sig_date_from,
    )
    return item_elements + sig_elements, layout


def _ics_estimated_content_height(item_count, blank_rows, blank_row_height):
    """Approximate flowable height above the ICS page footer."""
    return (
        ICS_HEADER_BLOCK_HEIGHT + ICS_TABLE_HEADER_HEIGHT
        + item_count * ICS_DATA_ROW_HEIGHT
        + blank_rows * blank_row_height
        + ICS_SIG_BLOCK_HEIGHT
    )


def _ics_footer_elements(
    styles, half_w, usable_h=None, content_height=None,
    page_num=1, page_total=1,
):
    """Footer title and page number, pinned near the bottom when space allows."""
    elements = []
    if usable_h is not None and content_height is not None:
        gap = usable_h - content_height - ICS_FOOTER_BLOCK_HEIGHT
        if gap > 4:
            elements.append(Spacer(1, gap))
    elements.append(Spacer(1, 0.2 * cm))
    page_label = f'Page {page_num}/{page_total}'
    footer = Table(
        [[
            Paragraph('Inventory Custodian Slip', styles['IcsFooter']),
            Paragraph(page_label, styles['IcsFooter']),
        ]],
        colWidths=[half_w, half_w],
    )
    footer.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(footer)
    return elements


def _ics_labeled_value(label, value, style):
    """ICS header field — label plus bold value (Appendix 59)."""
    text = escape(str(value)) if value not in (None, '') else ''
    if text:
        return Paragraph(f'<b>{label}</b> <b>{text}</b>', style)
    return Paragraph(f'<b>{label}</b>', style)


def _ics_supplier_block(site, ics):
    """ICS header supplier fields — supplier per slip, others from site settings."""
    return {
        'supplier': ics.supplier_name,
        'address': site.ics_supplier_address or ics.supplier_address,
        'po_number': site.ics_po_number or ics.po_number,
        'date': site.ics_header_date or ics.date,
        'mop': site.ics_mode_of_procurement or ics.mode_of_procurement,
    }


def _build_ics_card_elements(ics, styles):
    """Flowables for one ICS (Appendix 59) — COA Circular 2022-004 layout."""
    return _build_ics_group_elements([ics], styles)


def _build_ics_group_elements(
    ics_group, styles, *, line_items=None, page_num=1, page_total=1,
):
    """Flowables for one ICS page — single slip or combined same-entity group."""
    primary = ics_group[0]
    usable_w, usable_h = _ics_usable_dimensions()
    half_w = usable_w / 2
    elements = []

    site = SiteSettings.get_solo()
    received_by = primary.received_by
    received_from = primary.received_from or resolve_supply_officer(None)
    signatories = {
        'by_name': (
            (received_by.get_full_name() if received_by else '')
            or site.ics_received_by_name
        ),
        'from_name': (
            (received_from.get_full_name() if received_from else '')
            or site.ics_received_from_name
        ),
        'by_position': (
            primary.received_by_position
            or _user_office(received_by)
            or site.ics_received_by_position
        ),
        'from_position': (
            primary.received_from_position
            or _user_office(received_from)
            or site.ics_received_from_position
        ),
    }
    sig_date_by = str(primary.date_received_by or primary.date or _manila_today())
    sig_date_from = str(primary.date_received_from or primary.date or _manila_today())
    fund_cluster_label = _ics_fund_cluster_for_group(ics_group)
    supplier_block = _ics_supplier_block(site, primary)
    ics_no_label = (
        _ics_numbers_for_group(ics_group)
        if len(ics_group) > 1
        else primary.ics_no
    )
    left_w = usable_w * 0.48
    right_w = usable_w * 0.52

    # Appendix 59 / COA Circular 2022-004 — italic, top-right, outside header box
    elements.append(Paragraph('<i>Appendix 59</i>', styles['IcsAnnex']))
    elements.append(Paragraph('<i>COA Circular 2022-004</i>', styles['IcsAnnex']))
    elements.append(Spacer(1, 0.05 * cm))

    # Bordered header box — title, right-aligned supplier block, entity/fund bottom
    header_data = [
        [Paragraph('INVENTORY CUSTODIAN SLIP', styles['IcsHeaderTitle']), ''],
        [
            '',
            _ics_labeled_value('Supplier:', supplier_block['supplier'], styles['IcsLabelRight']),
        ],
        [
            '',
            _ics_labeled_value('Address:', supplier_block['address'], styles['IcsLabelRight']),
        ],
        [
            '',
            _ics_labeled_value('P.O. #:', supplier_block['po_number'], styles['IcsLabelRight']),
        ],
        [
            '',
            _ics_labeled_value('Date:', supplier_block['date'], styles['IcsLabelRight']),
        ],
        [
            '',
            _ics_labeled_value('MOP:', supplier_block['mop'], styles['IcsLabelRight']),
        ],
        [
            Paragraph(f'<b>Entity Name:</b> {escape(primary.entity_name)}', styles['IcsLabel']),
            '',
        ],
        [
            Paragraph(
                f'<b>Fund Cluster:</b> {escape(fund_cluster_label)}',
                styles['IcsLabel'],
            ),
            Paragraph(f'<b>ICS No.:</b> {escape(ics_no_label)}', styles['IcsLabelRight']),
        ],
    ]
    header_table = Table(header_data, colWidths=[left_w, right_w])
    header_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('SPAN', (0, 0), (1, 0)),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 1), (1, 5), 'RIGHT'),
        ('ALIGN', (1, 7), (1, 7), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 1), (1, 5), 1),
        ('BOTTOMPADDING', (0, 5), (1, 5), 8),
    ]))
    elements.append(header_table)

    items = line_items if line_items is not None else _ics_line_items_from_group(ics_group)
    body_elements, layout = _ics_body_table_elements(
        items, signatories, styles, usable_w, usable_h,
        sig_date_by, sig_date_from=sig_date_from,
    )
    elements.extend(body_elements)
    content_height = _ics_estimated_content_height(
        layout['item_count'], layout['blank_rows'], layout['blank_row_height'],
    )
    elements.extend(_ics_footer_elements(
        styles, half_w, usable_h=usable_h, content_height=content_height,
        page_num=page_num, page_total=page_total,
    ))
    return elements


def _spc_office_officer(particulars):
    """Extract end-user/office from SPC transaction particulars."""
    for prefix in ('Issued to ', 'Assigned to ', 'Returned from '):
        if particulars.startswith(prefix):
            return particulars[len(prefix):]
    return ''


def _coa_ledger_row_height_rules():
    """Compact row heights so header + ledger grid fits one landscape page."""
    return [
        ('ROWHEIGHT', (0, 0), (-1, 1), 16),
        ('ROWHEIGHT', (0, 2), (-1, -1), 10),
    ]


def _spc_form_table_style():
    """Government-form borders for SPC ledger grid."""
    rules = [
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
        ('ALIGN', (0, 2), (2, -1), 'CENTER'),
        ('ALIGN', (3, 2), (10, -1), 'CENTER'),
        ('ALIGN', (11, 2), (11, -1), 'RIGHT'),
        ('ALIGN', (12, 2), (12, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, 1), 'MIDDLE'),
        ('VALIGN', (0, 2), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        # Merged header cells
        ('SPAN', (0, 0), (0, 1)),
        ('SPAN', (1, 0), (1, 1)),
        ('SPAN', (2, 0), (2, 1)),
        ('SPAN', (3, 0), (6, 0)),
        ('SPAN', (7, 0), (9, 0)),
        ('SPAN', (10, 0), (10, 1)),
        ('SPAN', (11, 0), (11, 1)),
        ('SPAN', (12, 0), (12, 1)),
    ]
    # Unit Cost, Total Cost, Amount — peso glyph needs a Unicode TTF font.
    rules.extend(peso_table_font_rules((5, 6, 11)))
    rules.extend(_coa_ledger_row_height_rules())
    return TableStyle(rules)


def _spc_page_size():
    return landscape(A4)


def _spc_usable_width():
    return _spc_page_size()[0] - 3 * cm


def _scale_col_widths(weights):
    """Scale relative column weights to the SPC/SPLC printable page width."""
    usable = _spc_usable_width()
    total = sum(weights)
    return [usable * (w / total) for w in weights]


def _spc_col_widths():
    """SPC column widths — full landscape page width."""
    return _scale_col_widths([
        2.0,   # Date
        2.2,   # Reference
        2.2,   # Date of Expiration
        1.6,   # Receipt — Item No.
        1.0,   # Receipt — Qty.
        2.0,   # Receipt — Unit Cost
        2.0,   # Receipt — Total Cost
        1.6,   # Issue — Item No.
        1.0,   # Issue — Qty.
        3.5,   # Issue — Office/Officer
        1.0,   # Balance — Qty.
        2.0,   # Amount
        4.6,   # Remarks
    ])


def _splc_col_widths():
    """SPLC column widths — same full-page width as SPC tables."""
    return _scale_col_widths([
        2.0,   # Date
        2.2,   # Reference
        1.0,   # Receipt — Qty.
        2.0,   # Receipt — Unit Cost
        2.0,   # Receipt — Total Cost
        4.8,   # Issues/Transfers/Adjustment/s
        2.2,   # Adjusted Cost
        4.7,   # Repair — Nature of Repair
        2.8,   # Repair — Amount
    ])


SPC_COL_WIDTHS = _spc_col_widths()

SPC_LEDGER_HEADER = [
    [
        'Date', 'Reference', 'Date of\nExpiration',
        'Receipt', '', '', '',
        'Issue/Transfer/\nDisposal', '', '',
        'Balance', 'Amount', 'Remarks',
    ],
    [
        '', '', '',
        'Item No.', 'Qty.', 'Unit Cost', 'Total Cost',
        'Item No.', 'Qty.', 'Office/\nOfficer',
        'Qty.', '', '',
    ],
]

# Ledger body rows — fit header + grid on one landscape page (matches SPC/SPLC layout).
SPC_LEDGER_BODY_ROWS = 18
SPLC_LEDGER_BODY_ROWS = SPC_LEDGER_BODY_ROWS


def _spc_styles():
    """Paragraph styles for SPC cards (reused for single and bulk export)."""
    styles = _styles()
    styles.add(ParagraphStyle(
        name='SpcTitle',
        parent=styles['Normal'],
        fontSize=12,
        leading=14,
        alignment=1,
        spaceAfter=6,
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        name='SpcLabel',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name='SpcAnnex',
        parent=styles['Normal'],
        fontSize=9,
        alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='SpcTableCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        wordWrap='LTR',
    ))
    return styles


def _spc_transaction_cells(r, unit_cost):
    """Plain cell values for one SPC ledger row (shared by PDF and Excel export)."""
    receipt_item = r.get('receipt_item_no', '')
    receipt_qty = receipt_unit = receipt_total = ''
    issue_item = r.get('issue_item_no', '')
    issue_qty = ''
    if r.get('receipt_qty'):
        qty = r['receipt_qty']
        receipt_qty = str(qty)
        receipt_unit = _fmt_peso(unit_cost)
        receipt_total = _fmt_peso(float(unit_cost) * qty)
    if r.get('issue_qty'):
        issue_qty = str(r['issue_qty'])

    office = r.get('office_officer') or _spc_office_officer(r.get('particulars') or '')
    expiration = r.get('expiration_date')
    row_expiration = str(expiration) if expiration else ''
    balance = '' if r.get('balance') is None else str(r['balance'])

    return [
        str(r['date']),
        r['reference'],
        row_expiration,
        receipt_item,
        receipt_qty,
        receipt_unit,
        receipt_total,
        issue_item,
        issue_qty,
        office,
        balance,
        _fmt_peso(r['amount']) if r.get('amount') else '',
        r.get('particulars') or '',
    ]


def _spc_transaction_row(r, unit_cost, styles):
    """Convert one SPC transaction dict to a PDF table row."""
    cells = _spc_transaction_cells(r, unit_cost)
    office = cells[9]
    particulars = cells[12]
    cells[9] = Paragraph(escape(office), styles['SpcTableCell']) if office else ''
    cells[12] = Paragraph(escape(particulars), styles['SpcTableCell']) if particulars else ''
    return cells


def _build_spc_ledger_table(data_rows, styles):
    """SPC ledger grid padded to the official Annex A.2 row count."""
    data = list(SPC_LEDGER_HEADER)
    data.extend(data_rows)
    blank_rows = max(0, SPC_LEDGER_BODY_ROWS - len(data_rows))
    for _ in range(blank_rows):
        data.append([''] * 13)

    ledger_table = Table(data, colWidths=_spc_col_widths(), repeatRows=2)
    ledger_table.setStyle(_spc_form_table_style())
    return ledger_table


def _build_spc_card_elements(equipment, styles):
    """Flowables for one Semi-Expendable Property Card (Annex A.2)."""
    from equipment.models import Equipment

    # Always read fresh DB row so bulk export matches individual print.
    equipment = (
        Equipment.objects
        .select_related('category', 'department')
        .get(pk=equipment.pk)
    )
    usable_w = _spc_usable_width()
    elements = []

    annex_row = Table(
        [['', Paragraph('Annex A.2', styles['SpcAnnex'])]],
        colWidths=[usable_w - 2 * cm, 2 * cm],
    )
    annex_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(annex_row)
    elements.append(Paragraph('SEMI-EXPENDABLE PROPERTY CARD', styles['SpcTitle']))

    meta = [[
        Paragraph(f'<b>LGU:</b> {escape(spc_lgu_name())}', styles['SpcLabel']),
        Paragraph(f'<b>Fund:</b> {escape(spc_fund_label(equipment))}', styles['SpcLabel']),
    ]]
    meta_table = Table(meta, colWidths=[usable_w * 0.55, usable_w * 0.45])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(meta_table)

    prop_type = spc_semi_expendable_type(equipment)
    useful_life = spc_useful_life_label(equipment)
    prop_info = [
        [
            Paragraph(
                f'<b>Semi-expendable Property:</b> {escape(prop_type or "")}',
                styles['SpcLabel'],
            ),
            Paragraph(
                f'<b>Semi-expendable Property Number:</b> {escape(equipment.property_number)}',
                styles['SpcLabel'],
            ),
        ],
        [
            Paragraph(
                f'<b>Description:</b> {escape(spc_property_description(equipment))}',
                styles['SpcLabel'],
            ),
            Paragraph(
                f'<b>Estimated Useful Life:</b> {escape(useful_life)}',
                styles['SpcLabel'],
            ),
        ],
    ]
    prop_table = Table(prop_info, colWidths=[usable_w * 0.55, usable_w * 0.45])
    prop_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(prop_table)
    elements.append(Spacer(1, 0.2 * cm))

    unit_cost = effective_cost(equipment)
    transactions = get_spc_transactions(equipment)
    data_rows = [
        _spc_transaction_row(r, unit_cost, styles)
        for r in transactions
    ]
    elements.append(_build_spc_ledger_table(data_rows, styles))
    return elements


def _render_coa_card_pdf(elements):
    """Build a single-page landscape COA property card PDF (SPC / SPLC)."""
    ensure_peso_font()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=_spc_page_size(),
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    doc.build(elements)
    buffer.seek(0)
    return buffer


def _render_spc_pdf(elements):
    """Build a landscape SPC PDF from prepared flowables."""
    return _render_coa_card_pdf(elements)


def generate_spc_pdf(equipment):
    """Semi-Expendable Property Card (Annex A.2) — official COA template."""
    styles = _spc_styles()
    buffer = _render_spc_pdf(_build_spc_card_elements(equipment, styles))
    return buffer, f'SPC_{equipment.property_number}.pdf'


def generate_all_spc_pdf(equipment_list):
    """All Semi-Expendable Property Cards in one PDF — merges individual prints."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    items = list(equipment_list)
    if not items:
        raise ValueError('No semi-expendable equipment to export.')

    for equipment in items:
        buffer, _ = generate_spc_pdf(equipment)
        reader = PdfReader(buffer)
        writer.append(reader)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out, f'SPC_All_{len(items)}_items_{date.today()}.pdf'


def _splc_form_table_style():
    """Government-form borders for SPLC ledger grid (Annex A.3) — matches SPC table styling."""
    rules = [
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
        ('ALIGN', (0, 2), (1, -1), 'CENTER'),
        ('ALIGN', (2, 2), (4, -1), 'CENTER'),
        ('ALIGN', (5, 2), (5, -1), 'LEFT'),
        ('ALIGN', (6, 2), (6, -1), 'RIGHT'),
        ('ALIGN', (7, 2), (7, -1), 'LEFT'),
        ('ALIGN', (8, 2), (8, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, 1), 'MIDDLE'),
        ('VALIGN', (0, 2), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        # Merged header cells (two-row header like SPC)
        ('SPAN', (0, 0), (0, 1)),
        ('SPAN', (1, 0), (1, 1)),
        ('SPAN', (2, 0), (4, 0)),
        ('SPAN', (5, 0), (5, 1)),
        ('SPAN', (6, 0), (6, 1)),
        ('SPAN', (7, 0), (8, 0)),
    ]
    rules.extend(peso_table_font_rules((3, 4, 5, 6, 8)))
    rules.extend(_coa_ledger_row_height_rules())
    return TableStyle(rules)

SPLC_LEDGER_HEADER = [
    [
        'Date', 'Reference',
        'Receipt', '', '',
        'Issues/Transfers/\nAdjustment/s',
        'Adjusted Cost',
        'Repair History', '',
    ],
    [
        '', '',
        'Qty.', 'Unit Cost', 'Total Cost',
        '', '',
        'Nature of Repair', 'Amount',
    ],
]

def _splc_issues_transfer_label(r):
    """Format Issues/Transfers/Adjustments/s column — amount and description."""
    amount = r.get('issue_transfer_amount')
    label = (r.get('issue_transfer_label') or '').strip()
    if amount is not None and amount > 0:
        text = _fmt_peso(amount)
        if label:
            return f'{text} — {label}'
        return text
    return label


def _splc_transaction_cells(r, unit_cost):
    """Plain cell values for one SPLC ledger row (shared by PDF and Excel export)."""
    if r.get('is_repair'):
        return [
            str(r['date']),
            r['reference'],
            '', '', '',
            '',
            '',
            r.get('repair_nature') or '',
            _fmt_peso(r['repair_amount']) if r.get('repair_amount') else '',
        ]

    receipt_qty = receipt_unit = receipt_total = ''
    if r.get('receipt_qty'):
        qty = r['receipt_qty']
        row_unit = r.get('unit_cost')
        row_unit = unit_cost if row_unit is None else row_unit
        row_total = r.get('total_cost')
        if row_total is None:
            row_total = float(row_unit) * qty
        receipt_qty = str(qty)
        receipt_unit = _fmt_peso(row_unit)
        receipt_total = _fmt_peso(row_total)

    issues_text = _splc_issues_transfer_label(r)
    adjusted = r.get('adjusted_cost')
    adjusted_cell = _fmt_peso(adjusted) if adjusted is not None else ''

    return [
        str(r['date']),
        r['reference'],
        receipt_qty,
        receipt_unit,
        receipt_total,
        issues_text,
        adjusted_cell,
        '',
        '',
    ]


def _splc_transaction_row(r, unit_cost, styles):
    """Convert one SPLC transaction dict to a COA Annex A.3 PDF table row."""
    cells = _splc_transaction_cells(r, unit_cost)
    issues_text = cells[5]
    repair_nature = cells[7]
    cells[5] = Paragraph(escape(issues_text), styles['SpcTableCell']) if issues_text else ''
    cells[7] = Paragraph(escape(repair_nature), styles['SpcTableCell']) if repair_nature else ''
    return cells


def _build_splc_ledger_table(data_rows, styles):
    """SPLC ledger grid padded to the official Annex A.3 row count."""
    data = list(SPLC_LEDGER_HEADER)
    data.extend(data_rows)
    blank_rows = max(0, SPLC_LEDGER_BODY_ROWS - len(data_rows))
    for _ in range(blank_rows):
        data.append([''] * 9)

    ledger_table = Table(data, colWidths=_splc_col_widths(), repeatRows=2)
    ledger_table.setStyle(_splc_form_table_style())
    return ledger_table


def _build_splc_card_elements(equipment, styles):
    """Flowables for one Semi-Expendable Property Ledger Card (Annex A.3)."""
    from equipment.models import Equipment

    equipment = (
        Equipment.objects
        .select_related('category', 'department')
        .get(pk=equipment.pk)
    )
    usable_w = _spc_usable_width()
    elements = []

    annex_row = Table(
        [['', Paragraph('Annex A.3', styles['SpcAnnex'])]],
        colWidths=[usable_w - 2 * cm, 2 * cm],
    )
    annex_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(annex_row)
    elements.append(Paragraph('SEMI-EXPENDABLE PROPERTY LEDGER CARD', styles['SpcTitle']))

    meta = [[
        Paragraph(f'<b>LGU:</b> {escape(spc_lgu_name())}', styles['SpcLabel']),
        Paragraph(f'<b>Fund:</b> {escape(spc_fund_label(equipment))}', styles['SpcLabel']),
    ]]
    meta_table = Table(meta, colWidths=[usable_w * 0.55, usable_w * 0.45])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(meta_table)

    prop_type = spc_semi_expendable_type(equipment)
    useful_life = spc_useful_life_label(equipment)
    prop_info = [
        [
            Paragraph(
                f'<b>Semi-expendable Property:</b> {escape(prop_type or "")}',
                styles['SpcLabel'],
            ),
            Paragraph(
                f'<b>Semi-expendable Property Number:</b> {escape(equipment.property_number)}',
                styles['SpcLabel'],
            ),
        ],
        [
            Paragraph(
                f'<b>Description:</b> {escape(spc_property_description(equipment))}',
                styles['SpcLabel'],
            ),
            Paragraph(
                f'<b>Estimated Useful Life:</b> {escape(useful_life)}',
                styles['SpcLabel'],
            ),
        ],
    ]
    prop_table = Table(prop_info, colWidths=[usable_w * 0.55, usable_w * 0.45])
    prop_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(prop_table)
    elements.append(Spacer(1, 0.2 * cm))

    unit_cost = effective_cost(equipment)
    transactions = get_splc_transactions(equipment)
    data_rows = [_splc_transaction_row(r, unit_cost, styles) for r in transactions]
    elements.append(_build_splc_ledger_table(data_rows, styles))

    return elements


def generate_splc_pdf(equipment):
    """Semi-Expendable Property Ledger Card (Annex A.3) — official COA template."""
    styles = _spc_styles()
    buffer = _render_spc_pdf(_build_splc_card_elements(equipment, styles))
    return buffer, f'SPLC_{equipment.property_number}.pdf'


def generate_all_splc_pdf(equipment_list):
    """All Semi-Expendable Property Ledger Cards in one PDF — merges individual prints."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    items = list(equipment_list)
    if not items:
        raise ValueError('No semi-expendable equipment to export.')

    for equipment in items:
        buffer, _ = generate_splc_pdf(equipment)
        reader = PdfReader(buffer)
        writer.append(reader)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out, f'SPLC_All_{len(items)}_items_{date.today()}.pdf'


def generate_rpcsp_pdf():
    """Report on Physical Count of Semi-Expendable Property (RPCSP) + reconciliation."""
    ensure_peso_font()
    styles = _styles()
    rpcsp = get_rpcsp_data()
    elements = _header_block(
        styles,
        'REPORT ON PHYSICAL COUNT OF SEMI-EXPENDABLE PROPERTY (RPCSP)',
        'A.4',
    )

    elements.append(Paragraph(
        f'<b>Inventory Accuracy:</b> {rpcsp["accuracy"]}% &nbsp; '
        f'<b>Total Items:</b> {rpcsp["total"]} &nbsp; '
        f'<b>Discrepancies:</b> {rpcsp["discrepancies"]}',
        styles['Normal'],
    ))
    elements.append(Spacer(1, 0.4 * cm))

    data = [
        ['Property No.', 'Description', 'Account Code', 'Recorded', 'Physical', 'Variance', 'Amount', 'Status'],
    ]
    for item in rpcsp['items']:
        flag = ' *' if item['has_discrepancy'] else ''
        data.append([
            item['property_number'],
            item['description'][:30],
            item['account_code'],
            str(item['recorded_qty']),
            str(item['physical_qty']),
            str(item['variance']) + flag,
            _fmt_peso(item['amount']),
            item['status'],
        ])

    table = Table(data, repeatRows=1)
    rpcsp_style = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_COLOR),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ALT_ROW]),
        ('PADDING', (0, 0), (-1, -1), 3),
    ]
    rpcsp_style.extend(peso_table_font_rules((6,)))
    table.setStyle(TableStyle(rpcsp_style))
    elements.append(table)
    if rpcsp['discrepancies']:
        elements.append(Spacer(1, 0.2 * cm))
        elements.append(Paragraph(
            f'<i>* {rpcsp["discrepancies"]} item(s) with discrepancies flagged for reconciliation.</i>',
            styles['FormSubtitle'],
        ))
    return _build_pdf(elements, 'RPCSP')
