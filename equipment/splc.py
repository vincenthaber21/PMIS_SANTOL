"""Semi-Expendable Property Ledger Card (SPLC) — COA Annex A.3 accounting ledger rows."""
from decimal import Decimal, InvalidOperation

from .coa import effective_cost
from .spc import get_spc_transactions


def _decimal(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _repair_nature(maintenance_request):
    """Nature of repair for SPLC Repair History column."""
    desc = (maintenance_request.issue_description or '').strip()
    if desc.startswith('[COA-DEMO]'):
        desc = desc.replace('[COA-DEMO]', '').strip()
    notes = (maintenance_request.technician_notes or '').strip()
    cost = _decimal(maintenance_request.actual_cost or maintenance_request.estimated_cost)

    if cost >= Decimal('10000'):
        prefix = 'Major repair'
    elif cost > 0:
        prefix = 'Minor repair'
    else:
        prefix = 'Repair'

    nature = desc[:100] if desc else 'Unspecified'
    if notes and maintenance_request.repair_status == 'Completed':
        return f'{prefix}: {nature} ({notes[:60]})'
    return f'{prefix}: {nature}'


def get_splc_transactions(equipment):
    """
    SPLC ledger rows posted from source documents (JEV, IAR, maintenance records).

    Columns map to COA Annex A.3:
    - Receipt Qty / Unit Cost / Total Cost on acquisition
    - Issues/Transfers/Adjustments/s — peso amount issued, transferred, disposed, or adjusted via JEV
    - Adjusted Cost — book value (total cost less cumulative issues/transfers/adjustments)
    - Repair History — nature and amount from maintenance records
    """
    from maintenance.models import MaintenanceRequest

    rows = []
    unit_cost = _decimal(effective_cost(equipment))
    default_qty = max(int(equipment.quantity or 1), 1)
    total_cost = unit_cost * default_qty
    adjusted_cost = Decimal('0')

    entries = list(equipment.accounting_entries.order_by('created_at', 'jev_number'))
    acq_jev = next((entry for entry in entries if entry.entry_type == 'ACQUISITION'), None)
    has_issuance_jev = any(entry.entry_type == 'ISSUANCE' for entry in entries)

    if equipment.purchase_date:
        adjusted_cost = total_cost
        rows.append({
            'date': equipment.purchase_date,
            'reference': acq_jev.jev_number if acq_jev else 'IAR',
            'receipt_qty': default_qty,
            'unit_cost': unit_cost,
            'total_cost': total_cost,
            'issue_transfer_amount': None,
            'issue_transfer_label': '',
            'adjusted_cost': adjusted_cost,
            'is_repair': False,
        })

    for jev in entries:
        if jev.entry_type == 'ACQUISITION':
            continue

        trans_date = jev.created_at.date()
        amount = _decimal(jev.amount)

        if jev.entry_type == 'ISSUANCE':
            adjusted_cost = max(adjusted_cost - amount, Decimal('0'))
            rows.append({
                'date': trans_date,
                'reference': jev.jev_number,
                'receipt_qty': 0,
                'unit_cost': None,
                'total_cost': None,
                'issue_transfer_amount': amount,
                'issue_transfer_label': jev.particulars,
                'adjusted_cost': adjusted_cost,
                'is_repair': False,
            })
        elif jev.entry_type == 'RECLASSIFICATION':
            adjusted_cost = max(adjusted_cost - amount, Decimal('0'))
            rows.append({
                'date': trans_date,
                'reference': jev.jev_number,
                'receipt_qty': 0,
                'unit_cost': None,
                'total_cost': None,
                'issue_transfer_amount': amount,
                'issue_transfer_label': f'Adjustment — {jev.particulars}',
                'adjusted_cost': adjusted_cost,
                'is_repair': False,
            })

    for spc in get_spc_transactions(equipment):
        if spc.get('issue_qty'):
            if has_issuance_jev:
                continue
            issue_amt = unit_cost * (spc.get('issue_qty') or 1)
            adjusted_cost = max(adjusted_cost - issue_amt, Decimal('0'))
            label = spc.get('office_officer') or spc.get('particulars', '')
            rows.append({
                'date': spc['date'],
                'reference': spc['reference'],
                'receipt_qty': 0,
                'unit_cost': None,
                'total_cost': None,
                'issue_transfer_amount': issue_amt,
                'issue_transfer_label': label,
                'adjusted_cost': adjusted_cost,
                'is_repair': False,
            })

    for mr in MaintenanceRequest.objects.filter(equipment=equipment).order_by('date_opened'):
        repair_cost = _decimal(mr.actual_cost or mr.estimated_cost)
        repair_date = mr.completion_date or mr.date_opened
        rows.append({
            'date': repair_date,
            'reference': f'MR-{mr.pk:04d}',
            'receipt_qty': 0,
            'unit_cost': None,
            'total_cost': None,
            'issue_transfer_amount': None,
            'issue_transfer_label': '',
            'adjusted_cost': None,
            'is_repair': True,
            'repair_nature': _repair_nature(mr),
            'repair_amount': repair_cost if repair_cost > 0 else None,
        })

    rows.sort(key=lambda r: r['date'])
    return rows
