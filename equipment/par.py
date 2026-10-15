"""Property Acknowledgment Receipt (PAR) — creation, numbering, and status."""
from datetime import timedelta

from django.utils import timezone

from core.signatories import default_supply_officer_user, resolve_supply_officer

from .coa import LGU_NAME, CLASSIFICATION_PPE, effective_cost, update_coa_fields
from .models import PropertyAcknowledgmentReceipt, PropertyAcknowledgmentReceiptItem


def _equipment_description(equipment):
    """Brief description including serial number when available."""
    parts = [equipment.display_name]
    if equipment.brand or equipment.model:
        parts.append(f'({equipment.brand} {equipment.model})'.strip())
    if equipment.serial_number:
        parts.append(f'S/N: {equipment.serial_number}')
    return ' '.join(parts)


def _equipment_unit(equipment):
    """Default unit of measure from category when no dedicated field exists."""
    if equipment.category:
        cat = equipment.category.name.lower()
        if 'furniture' in cat:
            return 'set'
        if 'vehicle' in cat:
            return 'unit'
    return 'unit'


def generate_par_no(issue_date):
    """
    Control number format SERIAL-MM-YYYY (e.g. 0001-07-2026).
    Serial resets to 0001 each calendar year (one series per year).
    """
    year = issue_date.year
    month = issue_date.month
    max_serial = 0
    for par_no in (
        PropertyAcknowledgmentReceipt.objects
        .filter(par_no__endswith=f'-{year}')
        .values_list('par_no', flat=True)
    ):
        try:
            serial = int(par_no.split('-')[0])
            max_serial = max(max_serial, serial)
        except (ValueError, IndexError):
            continue
    return f'{max_serial + 1:04d}-{month:02d}-{year}'


def supersede_active_pars_for_equipment(equipment, new_par):
    """Mark active/due PARs for this equipment as Superseded, linking to the replacement."""
    old_pars = (
        PropertyAcknowledgmentReceipt.objects
        .filter(
            items__equipment=equipment,
            status__in=[
                PropertyAcknowledgmentReceipt.STATUS_ACTIVE,
                PropertyAcknowledgmentReceipt.STATUS_DUE,
            ],
        )
        .exclude(pk=new_par.pk)
        .distinct()
    )
    for old_par in old_pars:
        old_par.status = PropertyAcknowledgmentReceipt.STATUS_SUPERSEDED
        old_par.superseded_by = new_par
        old_par.save(update_fields=['status', 'superseded_by'])


def create_par_for_issuance(
    equipment,
    end_user,
    custodian=None,
    reference_type='',
    reference_id=None,
    issue_date=None,
):
    """
    Create a PAR for PPE issuance. Returns the PAR or None if not PPE.
    Supersedes prior active PARs for the same equipment on reassignment.
    end_user may be blank when the item is not yet assigned to anyone.
    """
    update_coa_fields(equipment)
    if equipment.classification != CLASSIFICATION_PPE:
        return None

    if reference_type and reference_id is not None:
        existing = PropertyAcknowledgmentReceipt.objects.filter(
            reference_type=reference_type,
            reference_id=str(reference_id),
        ).first()
        if existing:
            existing.refresh_status()
            return existing

    if issue_date is None:
        issue_date = timezone.now().date()

    renewal_due = issue_date + timedelta(days=3 * 365)
    par = PropertyAcknowledgmentReceipt.objects.create(
        lgu=LGU_NAME,
        fund=equipment.fund or 'General Fund',
        par_no=generate_par_no(issue_date),
        end_user=end_user,
        custodian=resolve_supply_officer(custodian),
        date_received=issue_date,
        date_issued=issue_date,
        renewal_due_date=renewal_due,
        status=PropertyAcknowledgmentReceipt.STATUS_ACTIVE,
        reference_type=reference_type or '',
        reference_id=str(reference_id) if reference_id is not None else None,
    )

    supersede_active_pars_for_equipment(equipment, par)

    qty = max(int(equipment.quantity or 1), 1)
    PropertyAcknowledgmentReceiptItem.objects.create(
        par=par,
        equipment=equipment,
        quantity=qty,
        unit=_equipment_unit(equipment),
        description=_equipment_description(equipment),
        property_number=equipment.property_number,
        date_acquired=equipment.purchase_date,
        amount=effective_cost(equipment) * qty,
    )

    par.refresh_status()
    return par


def _resolve_par_users(equipment, end_user=None, custodian=None):
    """Pick end-user / issuing supply officer for a PAR."""
    resolved_end_user = end_user or equipment.assigned_user
    resolved_custodian = resolve_supply_officer(custodian)
    return resolved_end_user, resolved_custodian


def create_par_for_equipment(equipment, created_by=None):
    """
    Create a PAR when PPE equipment is registered.
    Returns the PAR or None if the item is not PPE or no supply officer exists.
    An unassigned item still gets a PAR; Received by stays blank until assignment.
    """
    update_coa_fields(equipment)
    if equipment.classification != CLASSIFICATION_PPE:
        return None

    active = get_active_par_for_equipment(equipment)
    if active:
        return active

    end_user, custodian = _resolve_par_users(equipment, custodian=created_by)
    if not custodian:
        return None

    return create_par_for_issuance(
        equipment,
        end_user=end_user,
        custodian=custodian,
        reference_type='Equipment',
        reference_id=equipment.pk,
        issue_date=equipment.purchase_date,
    )


def ensure_par_for_equipment(equipment, created_by=None):
    """Return the active PAR for equipment, creating one when missing."""
    return create_par_for_equipment(equipment, created_by=created_by) or get_active_par_for_equipment(equipment)


def ensure_par_for_queryset(queryset, created_by=None):
    """Create missing PAR records for PPE equipment in a queryset."""
    equipment_ids_with_par = set(
        PropertyAcknowledgmentReceiptItem.objects.filter(
            equipment__in=queryset,
            par__status__in=[
                PropertyAcknowledgmentReceipt.STATUS_ACTIVE,
                PropertyAcknowledgmentReceipt.STATUS_DUE,
            ],
        ).values_list('equipment_id', flat=True)
    )
    created = 0
    for equipment in queryset:
        if equipment.pk in equipment_ids_with_par:
            continue
        if create_par_for_equipment(equipment, created_by=created_by):
            created += 1
    return created


def get_active_par_for_equipment(equipment):
    """Return the current (non-superseded) PAR for an equipment item, if any."""
    item = (
        PropertyAcknowledgmentReceiptItem.objects
        .filter(
            equipment=equipment,
            par__status__in=[
                PropertyAcknowledgmentReceipt.STATUS_ACTIVE,
                PropertyAcknowledgmentReceipt.STATUS_DUE,
            ],
        )
        .select_related('par', 'par__end_user', 'par__custodian')
        .order_by('-par__date_issued')
        .first()
    )
    if item:
        item.par.refresh_status(save=True)
    return item.par if item else None


def fix_par_custodian(par, save=True):
    """Ensure the PAR custodian is a supply officer, not the end user."""
    officer = resolve_supply_officer(par.custodian)
    if officer and par.custodian_id != officer.pk:
        par.custodian = officer
        if save:
            par.save(update_fields=['custodian_id'])
    return par


def sync_par_end_user(par, save=True):
    """Keep PAR end_user aligned with the equipment assignee."""
    item = par.items.select_related('equipment__assigned_user').first()
    if item and item.equipment.assigned_user_id and par.end_user_id != item.equipment.assigned_user_id:
        par.end_user = item.equipment.assigned_user
        if save:
            par.save(update_fields=['end_user_id'])
    return par


def refresh_all_par_statuses():
    """Refresh renewal status for all non-superseded PARs."""
    for par in PropertyAcknowledgmentReceipt.objects.exclude(
        status=PropertyAcknowledgmentReceipt.STATUS_SUPERSEDED,
    ):
        sync_par_end_user(par)
        fix_par_custodian(par)
        par.refresh_status()


def _fund_cluster_from_equipment(equipment):
    """Fund cluster label from equipment category and fund source — e.g. IT / Fund 201."""
    if not equipment:
        return '—'
    category_code = ''
    fund_code = ''
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


def _entity_name_from_user(user):
    """PAR Entity Name from the assigned end-user — department, then name, then role."""
    if not user:
        return ''
    if getattr(user, 'department_id', None):
        return str(user.department)
    full_name = (user.get_full_name() or user.username or '').strip()
    if full_name:
        return full_name
    if getattr(user, 'role_id', None):
        return user.role.name
    return ''


def _fund_cluster_labels(equipment_rows):
    """Unique fund-cluster labels across equipment rows."""
    clusters = []
    seen = set()
    for eq in equipment_rows:
        if not eq:
            continue
        label = _fund_cluster_from_equipment(eq)
        if label and label != '—' and label not in seen:
            seen.add(label)
            clusters.append(label)
    return clusters


def par_entity_name(par=None, equipment=None, equipment_list=None, end_user=None):
    """Office / department line for the PAR header (Appendix 71)."""
    from_assigned = _entity_name_from_user(end_user)
    if from_assigned:
        return from_assigned
    if par:
        if par.end_user_id:
            from_par_user = _entity_name_from_user(par.end_user)
            if from_par_user:
                return from_par_user
        item = par.items.select_related('equipment__department').first()
        if item and item.equipment.department_id:
            return str(item.equipment.department)
        if (par.lgu or '').strip():
            return par.lgu
    for eq in equipment_list or ([equipment] if equipment else []):
        if eq and eq.department_id:
            return str(eq.department)
    return LGU_NAME


def par_fund_cluster_display(par=None, equipment=None, equipment_list=None):
    """Fund cluster line for the PAR header (Appendix 71)."""
    if par:
        equipment_rows = [
            item.equipment
            for item in par.items.select_related(
                'equipment__category', 'equipment__fund_source',
            )
        ]
        clusters = _fund_cluster_labels(equipment_rows)
        if clusters:
            return ', '.join(clusters)
    clusters = _fund_cluster_labels(
        equipment_list or ([equipment] if equipment else []),
    )
    if clusters:
        return ', '.join(clusters)
    return '—'
