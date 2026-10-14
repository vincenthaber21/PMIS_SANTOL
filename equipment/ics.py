"""Inventory Custodian Slip (ICS) — creation, numbering, and lookup."""
from django.utils import timezone

from core.models import SiteSettings
from core.signatories import (
    default_supply_officer_user,
    is_supply_officer,
    resolve_supply_officer,
    supply_officer_position,
)

from .coa import LGU_NAME, CLASSIFICATION_PPE, effective_cost, update_coa_fields
from .models import InventoryCustodianSlip, InventoryCustodianSlipItem


def _equipment_description(equipment):
    """Brief description for ICS line item."""
    parts = [equipment.display_name]
    if equipment.brand or equipment.model:
        parts.append(f'({equipment.brand} {equipment.model})'.strip())
    if equipment.serial_number:
        parts.append(f'S/N: {equipment.serial_number}')
    return ' '.join(parts)


def _user_position(user, default=''):
    """Position/office line for ICS signature block."""
    if not user:
        return default
    if is_supply_officer(user):
        return supply_officer_position(user, include_department=True)
    if getattr(user, 'department', None):
        return f'Head, {user.department.name}'
    return str(user.role) if user.role else default


def ics_fund_cluster_display(ics):
    """Fund cluster line for ICS header — e.g. IT / Fund 201."""
    item = (
        ics.items
        .select_related('equipment__category', 'equipment__fund_source')
        .first()
    )
    category_code = ''
    fund_code = (ics.fund_cluster or '').strip()
    if item and item.equipment_id:
        equipment = item.equipment
        if equipment.category_id:
            category_code = (
                equipment.category.property_type_code.strip().upper()
                if equipment.category.property_type_code
                else 'OT'
            )
        if equipment.fund_source_id:
            fund_code = equipment.fund_source.code.strip()
    if category_code and fund_code:
        return f'{category_code} / Fund {fund_code}'
    if category_code:
        return category_code
    if fund_code:
        return f'Fund {fund_code}'
    return '—'


def _resolve_ics_users(equipment, end_user=None, custodian=None):
    """Pick received-by / received-from users for an ICS."""
    fallback = default_supply_officer_user()
    received_by = end_user or equipment.assigned_user or custodian or fallback
    received_from = resolve_supply_officer(custodian)
    return received_by, received_from


def generate_ics_no(issue_date):
    """
    Control number format SERIAL-MM-YYYY (e.g. 0001-06-2025).
    Serial resets each calendar year.
    """
    year = issue_date.year
    month = issue_date.month
    max_serial = 0
    for ics_no in (
        InventoryCustodianSlip.objects
        .filter(ics_no__endswith=f'-{year}')
        .values_list('ics_no', flat=True)
    ):
        try:
            serial = int(ics_no.split('-')[0])
            max_serial = max(max_serial, serial)
        except (ValueError, IndexError):
            continue
    return f'{max_serial + 1:04d}-{month:02d}-{year}'


def supersede_active_ics_for_equipment(equipment, new_ics):
    """Mark active ICS records for this equipment as Superseded."""
    old_slips = (
        InventoryCustodianSlip.objects
        .filter(
            items__equipment=equipment,
            status=InventoryCustodianSlip.STATUS_ACTIVE,
        )
        .exclude(pk=new_ics.pk)
        .distinct()
    )
    for old_ics in old_slips:
        old_ics.status = InventoryCustodianSlip.STATUS_SUPERSEDED
        old_ics.superseded_by = new_ics
        old_ics.save(update_fields=['status', 'superseded_by'])


def _create_ics_record(
    equipment,
    received_by,
    received_from,
    reference_type,
    reference_id,
    issue_date=None,
):
    """Persist an ICS header and line item for one equipment record."""
    if issue_date is None:
        issue_date = equipment.purchase_date or timezone.now().date()

    fund_cluster = ''
    if equipment.fund_source_id:
        fund_cluster = equipment.fund_source.code

    entity_name = str(equipment.department) if equipment.department_id else LGU_NAME
    supplier_name = str(equipment.supplier) if equipment.supplier_id else ''
    supplier_address = equipment.supplier.address if equipment.supplier_id else ''
    mop = str(equipment.mode_of_procurement) if equipment.mode_of_procurement_id else ''

    unit_cost = effective_cost(equipment)
    qty = equipment.quantity or 1
    total_cost = unit_cost * qty

    site = SiteSettings.get_solo()
    ics = InventoryCustodianSlip.objects.create(
        lgu=LGU_NAME,
        entity_name=entity_name,
        fund_cluster=fund_cluster,
        fund=equipment.fund or 'General Fund',
        ics_no=generate_ics_no(issue_date),
        supplier_name=supplier_name,
        supplier_address=supplier_address,
        po_number=equipment.purchase_order_no or '',
        date=issue_date,
        mode_of_procurement=mop,
        received_by=received_by,
        received_from=received_from,
        received_by_position=(
            site.ics_received_by_position
            or _user_position(received_by, 'End User')
        ),
        received_from_position=(
            site.ics_received_from_position
            or _user_position(received_from, 'Supply Officer')
        ),
        date_received_by=issue_date,
        date_received_from=issue_date,
        status=InventoryCustodianSlip.STATUS_ACTIVE,
        reference_type=reference_type or '',
        reference_id=str(reference_id) if reference_id is not None else None,
    )

    supersede_active_ics_for_equipment(equipment, ics)

    InventoryCustodianSlipItem.objects.create(
        ics=ics,
        equipment=equipment,
        quantity=qty,
        unit=equipment.unit or 'unit',
        description=_equipment_description(equipment),
        amount=total_cost,
        inventory_item_no=equipment.property_number,
        estimated_unit_cost=unit_cost,
        total_cost=total_cost,
        useful_life=equipment.estimated_useful_life or 5,
    )

    return ics


def create_ics_for_equipment(equipment, created_by=None):
    """
    Create an ICS when semi-expendable equipment is registered.
    Returns the ICS or None if the item is PPE.
    """
    update_coa_fields(equipment)
    if equipment.classification == CLASSIFICATION_PPE:
        return None

    active = get_active_ics_for_equipment(equipment)
    if active:
        return active

    received_by, received_from = _resolve_ics_users(equipment, custodian=created_by)
    if not received_by or not received_from:
        return None

    return _create_ics_record(
        equipment,
        received_by=received_by,
        received_from=received_from,
        reference_type='Equipment',
        reference_id=equipment.pk,
        issue_date=equipment.purchase_date,
    )


def ensure_ics_for_equipment(equipment, created_by=None):
    """Return the active ICS for equipment, creating one when missing."""
    return create_ics_for_equipment(equipment, created_by=created_by) or get_active_ics_for_equipment(equipment)


def ensure_ics_for_queryset(queryset, created_by=None):
    """Create missing ICS records for semi-expendable equipment in a queryset."""
    equipment_ids_with_ics = set(
        InventoryCustodianSlipItem.objects.filter(
            equipment__in=queryset,
            ics__status=InventoryCustodianSlip.STATUS_ACTIVE,
        ).values_list('equipment_id', flat=True)
    )
    created = 0
    for equipment in queryset:
        if equipment.pk in equipment_ids_with_ics:
            continue
        if create_ics_for_equipment(equipment, created_by=created_by):
            created += 1
    return created


def create_ics_for_issuance(
    equipment,
    end_user,
    custodian=None,
    reference_type='',
    reference_id=None,
    issue_date=None,
):
    """
    Create an ICS for semi-expendable issuance. Returns the ICS or None if PPE.
    Supersedes prior active ICS records for the same equipment on reassignment.
    """
    update_coa_fields(equipment)
    if equipment.classification == CLASSIFICATION_PPE:
        return None

    if not end_user:
        return None

    if reference_type and reference_id is not None:
        existing = InventoryCustodianSlip.objects.filter(
            reference_type=reference_type,
            reference_id=str(reference_id),
        ).first()
        if existing:
            return existing

    received_by, received_from = _resolve_ics_users(equipment, end_user=end_user, custodian=custodian)
    return _create_ics_record(
        equipment,
        received_by=received_by,
        received_from=received_from,
        reference_type=reference_type,
        reference_id=reference_id,
        issue_date=issue_date,
    )


def get_active_ics_for_equipment(equipment):
    """Return the current (non-superseded) ICS for an equipment item, if any."""
    item = (
        InventoryCustodianSlipItem.objects
        .filter(
            equipment=equipment,
            ics__status=InventoryCustodianSlip.STATUS_ACTIVE,
        )
        .select_related('ics', 'ics__received_by', 'ics__received_from')
        .order_by('-ics__date')
        .first()
    )
    return item.ics if item else None
