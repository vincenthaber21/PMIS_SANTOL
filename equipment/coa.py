"""COA Circular 3.1 helpers — classification, account mapping, JEV generation."""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

# LGU name for COA forms (Province/City/Municipality)
LGU_NAME = getattr(settings, 'LGU_NAME', 'COMPREHENSIVE AGRARIAN REFORM PROGRAM')

FUND_CHOICES = [
    ('General Fund', 'General Fund'),
    ('Special Education Fund', 'Special Education Fund'),
    ('Trust Fund', 'Trust Fund'),
    ('SEF', 'SEF'),
]


def get_fund_choices():
    """Return active fund sources for dropdowns, with static fallback."""
    try:
        from .models import FundSource
        active = FundSource.objects.filter(status=FundSource.STATUS_ACTIVE).order_by('code')
        if active.exists():
            return [(f.name, f.display_label) for f in active]
    except Exception:
        pass
    return FUND_CHOICES

CLASSIFICATION_PPE = 'PPE'
CLASSIFICATION_SEMI = 'Semi-Expendable'
CLASSIFICATION_LOW = 'Low-Value Semi-Expendable'

CLASSIFICATION_CHOICES = [
    (CLASSIFICATION_PPE, 'PPE'),
    (CLASSIFICATION_SEMI, 'Semi-Expendable'),
    (CLASSIFICATION_LOW, 'Low-Value Semi-Expendable'),
]

SEMI_EXPENDABLE_CLASSIFICATIONS = (CLASSIFICATION_SEMI, CLASSIFICATION_LOW)

PPE_THRESHOLD = Decimal('50000')
LOW_VALUE_THRESHOLD = Decimal('5000')

# Default accounts when category mapping is missing
DEFAULT_ASSET_ACCOUNT = '10405990'
DEFAULT_EXPENSE_ACCOUNT = '50203210'
ACQUISITION_CREDIT_ACCOUNT = '10101010'


def effective_cost(equipment):
    """Return the cost used for COA classification."""
    cost = equipment.acquisition_cost
    if cost is None or cost <= 0:
        cost = equipment.purchase_cost
    return Decimal(str(cost or 0))


def all_recognition_criteria_met(equipment):
    return all([
        equipment.criterion_future_benefits,
        equipment.criterion_measurable_cost,
        equipment.criterion_useful_life,
        equipment.criterion_not_for_resale,
    ])


def classify_equipment(equipment):
    """
    COA Circular 3.1 classification rules.
    cost >= 50000 AND all 4 criteria True → PPE
    cost <= 5000 → Low-Value Semi-Expendable
    else → Semi-Expendable
    """
    cost = effective_cost(equipment)
    if cost >= PPE_THRESHOLD and all_recognition_criteria_met(equipment):
        return CLASSIFICATION_PPE
    if cost <= LOW_VALUE_THRESHOLD:
        return CLASSIFICATION_LOW
    return CLASSIFICATION_SEMI


def map_account_code(equipment):
    """Auto-map equipment category to Annex B semi-expendable account code."""
    from .models import ChartOfAccount

    if not equipment.category_id:
        return DEFAULT_ASSET_ACCOUNT

    coa = (
        ChartOfAccount.objects
        .filter(account_type='asset', categories=equipment.category)
        .first()
    )
    return coa.code if coa else DEFAULT_ASSET_ACCOUNT


def expense_account_for_issuance(equipment):
    """Return expense account for semi-expendable issuance."""
    from .models import ChartOfAccount

    if equipment.category_id:
        coa = (
            ChartOfAccount.objects
            .filter(account_type='expense_issuance', categories=equipment.category)
            .first()
        )
        if coa:
            return coa.code
    return DEFAULT_EXPENSE_ACCOUNT


def update_coa_fields(equipment):
    """Recompute classification and account code on equipment."""
    equipment.classification = classify_equipment(equipment)
    equipment.coa_account_code = map_account_code(equipment)
    return equipment.classification


def preview_coa_classification(
    *,
    acquisition_cost=None,
    category_id=None,
    criterion_future_benefits=True,
    criterion_measurable_cost=True,
    criterion_useful_life=True,
    criterion_not_for_resale=True,
):
    """
    Return COA classification preview for unsaved form data.
    Uses the same rules as reports/coa/ and Equipment.save().
    """
    from .models import Category, Equipment

    eq = Equipment(
        acquisition_cost=Decimal(str(acquisition_cost or 0)),
        criterion_future_benefits=bool(criterion_future_benefits),
        criterion_measurable_cost=bool(criterion_measurable_cost),
        criterion_useful_life=bool(criterion_useful_life),
        criterion_not_for_resale=bool(criterion_not_for_resale),
    )
    if category_id:
        try:
            eq.category = Category.objects.get(pk=int(category_id))
        except (Category.DoesNotExist, TypeError, ValueError):
            pass

    classification = classify_equipment(eq)
    account_code = map_account_code(eq)
    cost = effective_cost(eq)
    all_criteria = all_recognition_criteria_met(eq)
    form_type = 'PAR' if classification == CLASSIFICATION_PPE else 'ICS'
    semi_expendable = classification in SEMI_EXPENDABLE_CLASSIFICATIONS

    if cost >= PPE_THRESHOLD and all_criteria:
        rule = f'Cost ≥ ₱{PPE_THRESHOLD:,.0f} and all recognition criteria met → PPE'
    elif cost <= LOW_VALUE_THRESHOLD:
        rule = f'Cost ≤ ₱{LOW_VALUE_THRESHOLD:,.0f} → Low-Value Semi-Expendable'
    else:
        rule = (
            f'Cost between ₱{LOW_VALUE_THRESHOLD:,.0f} and ₱{PPE_THRESHOLD:,.0f}, '
            'or PPE criteria not fully met → Semi-Expendable'
        )

    return {
        'classification': classification,
        'coa_account_code': account_code,
        'form_type': form_type,
        'effective_cost': float(cost),
        'all_criteria_met': all_criteria,
        'semi_expendable': semi_expendable,
        'ppe_threshold': float(PPE_THRESHOLD),
        'low_value_threshold': float(LOW_VALUE_THRESHOLD),
        'rule': rule,
    }


def apply_coa_standards_to_all():
    """
    Recompute and persist COA classification + account code for every equipment item.
    Returns the number of records updated.
    """
    from .models import Equipment

    updated = 0
    for eq in Equipment.objects.select_related('category').iterator():
        old_classification = eq.classification
        old_account = eq.coa_account_code
        update_coa_fields(eq)
        if eq.classification != old_classification or eq.coa_account_code != old_account:
            eq.save(update_fields=['classification', 'coa_account_code', 'updated_at'])
            updated += 1
    return updated


def _next_jev_number():
    from .models import AccountingEntry
    today = timezone.now().date()
    prefix = f'JEV-{today.year}-'
    last = (
        AccountingEntry.objects
        .filter(jev_number__startswith=prefix)
        .order_by('-jev_number')
        .first()
    )
    if last:
        try:
            seq = int(last.jev_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'{prefix}{seq:04d}'


def create_accounting_entry(
    equipment,
    entry_type,
    debit_account,
    credit_account,
    amount,
    particulars,
    reference_type='',
    reference_id=None,
    created_by=None,
):
    """Create a JEV accounting entry (Annex C) linked to equipment."""
    from .models import AccountingEntry

    if reference_type and reference_id is not None:
        existing = AccountingEntry.objects.filter(
            equipment=equipment,
            entry_type=entry_type,
            reference_type=reference_type,
            reference_id=str(reference_id),
        ).first()
        if existing:
            return existing

    return AccountingEntry.objects.create(
        equipment=equipment,
        entry_type=entry_type,
        jev_number=_next_jev_number(),
        debit_account=debit_account,
        credit_account=credit_account,
        amount=amount,
        fund=equipment.fund or 'General Fund',
        particulars=particulars,
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id is not None else None,
        created_by=created_by,
    )


def create_acquisition_entry(equipment, created_by=None):
    """JEV at moment of acquisition."""
    from .models import AccountingEntry

    existing = AccountingEntry.objects.filter(
        equipment=equipment,
        entry_type='ACQUISITION',
    ).first()
    if existing:
        return existing

    amount = effective_cost(equipment)
    if amount <= 0:
        return None

    asset_account = equipment.coa_account_code or map_account_code(equipment)
    return create_accounting_entry(
        equipment=equipment,
        entry_type='ACQUISITION',
        debit_account=asset_account,
        credit_account=ACQUISITION_CREDIT_ACCOUNT,
        amount=amount,
        particulars=(
            f'Acquisition of {equipment.name} '
            f'(Property No. {equipment.property_number})'
        ),
        reference_type='Equipment',
        reference_id=equipment.pk,
        created_by=created_by,
    )


def create_issuance_entry(equipment, end_user_name, reference_type='', reference_id=None, created_by=None):
    """Expense-on-issuance JEV for semi-expendable / low-value items."""
    from .models import AccountingEntry

    if equipment.classification == CLASSIFICATION_PPE:
        return None

    existing = AccountingEntry.objects.filter(
        equipment=equipment,
        entry_type='ISSUANCE',
    ).first()
    if existing:
        return existing

    amount = effective_cost(equipment)
    if amount <= 0:
        return None

    asset_account = equipment.coa_account_code or map_account_code(equipment)
    expense_account = expense_account_for_issuance(equipment)

    return create_accounting_entry(
        equipment=equipment,
        entry_type='ISSUANCE',
        debit_account=expense_account,
        credit_account=asset_account,
        amount=amount,
        particulars=(
            f'Expense on issuance of {equipment.name} '
            f'to {end_user_name} (Property No. {equipment.property_number})'
        ),
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )


def create_reclassification_entry(equipment, old_classification, created_by=None):
    """JEV when classification changes."""
    if old_classification == equipment.classification:
        return None

    amount = effective_cost(equipment)
    if amount <= 0:
        return None

    old_account = DEFAULT_ASSET_ACCOUNT
    new_account = equipment.coa_account_code or map_account_code(equipment)

    return create_accounting_entry(
        equipment=equipment,
        entry_type='RECLASSIFICATION',
        debit_account=new_account,
        credit_account=old_account,
        amount=amount,
        particulars=(
            f'Reclassification of {equipment.name} from {old_classification} '
            f'to {equipment.classification}'
        ),
        reference_type='Equipment',
        reference_id=equipment.pk,
        created_by=created_by,
    )


def process_issuance(equipment, end_user, custodian=None, reference_type='', reference_id=None, created_by=None):
    """
    Side effect of issuance via borrowing or assignment.
    Returns form type: 'PAR' for PPE, 'ICS' for semi-expendable/low-value.
  """
    update_coa_fields(equipment)

    end_user_name = ''
    if end_user:
        end_user_name = end_user.get_full_name() or end_user.username
    else:
        end_user_name = 'End User'

    form_type = 'PAR' if equipment.classification == CLASSIFICATION_PPE else 'ICS'

    entry = None
    if form_type == 'ICS':
        entry = create_issuance_entry(
            equipment,
            end_user_name,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )

    par = None
    ics = None
    if form_type == 'PAR':
        from .par import create_par_for_issuance
        par = create_par_for_issuance(
            equipment,
            end_user=end_user,
            custodian=custodian,
            reference_type=reference_type,
            reference_id=reference_id,
        )
    else:
        from .ics import create_ics_for_issuance
        ics = create_ics_for_issuance(
            equipment,
            end_user=end_user,
            custodian=custodian,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    return {
        'form_type': form_type,
        'accounting_entry': entry,
        'end_user_name': end_user_name,
        'custodian': custodian,
        'par': par,
        'ics': ics,
    }


def get_issuance_events(equipment=None):
    """
    Collect issuance events from borrowing approvals and assignment history.
    No duplicate storage — reads existing records.
    """
    from borrowing.models import BorrowRequest
    from .models import EquipmentAssignmentHistory

    events = []

    borrow_qs = BorrowRequest.objects.filter(approval_status='Approved').select_related(
        'employee', 'equipment', 'approver', 'equipment__category', 'equipment__department'
    )
    if equipment:
        borrow_qs = borrow_qs.filter(equipment=equipment)

    for br in borrow_qs.order_by('-borrow_date'):
        eq = br.equipment
        update_coa_fields(eq)
        form_type = 'PAR' if eq.classification == CLASSIFICATION_PPE else 'ICS'
        events.append({
            'date': br.borrow_date,
            'form_type': form_type,
            'equipment': eq,
            'end_user': br.employee,
            'custodian': br.approver,
            'reference_type': 'BorrowRequest',
            'reference_id': br.pk,
            'property_number': eq.property_number,
            'amount': effective_cost(eq),
            'fund': eq.fund,
        })

    assign_qs = EquipmentAssignmentHistory.objects.filter(
        notes__in=('Assigned', 'Reassigned'),
        user__isnull=False,
    ).select_related('equipment', 'user', 'changed_by', 'equipment__category', 'equipment__department')
    if equipment:
        assign_qs = assign_qs.filter(equipment=equipment)

    for ah in assign_qs.order_by('-assigned_at'):
        eq = ah.equipment
        update_coa_fields(eq)
        form_type = 'PAR' if eq.classification == CLASSIFICATION_PPE else 'ICS'
        events.append({
            'date': ah.assigned_at.date(),
            'form_type': form_type,
            'equipment': eq,
            'end_user': ah.user,
            'custodian': ah.changed_by,
            'reference_type': 'EquipmentAssignmentHistory',
            'reference_id': ah.pk,
            'property_number': eq.property_number,
            'amount': effective_cost(eq),
            'fund': eq.fund,
        })

    events.sort(key=lambda e: e['date'], reverse=True)
    return events


def get_semi_expendable_equipment():
    """Queryset of active semi-expendable items for SPC (shared by UI and PDF export)."""
    from .models import Equipment

    return (
        Equipment.objects
        .select_related('category', 'department')
        .prefetch_related('borrow_requests', 'assignment_history')
        .exclude(status='Retired')
        .filter(classification__in=SEMI_EXPENDABLE_CLASSIFICATIONS)
        .order_by('property_number')
    )


def get_ppe_equipment():
    """Queryset of active PPE items (≥ ₱50,000) for PAR register and PDF export."""
    from .models import Equipment

    return (
        Equipment.objects
        .select_related('category', 'department', 'assigned_user', 'supplier', 'fund_source', 'property_status')
        .prefetch_related('borrow_requests', 'assignment_history')
        .exclude(status='Retired')
        .filter(classification=CLASSIFICATION_PPE)
        .order_by('property_number')
    )


def get_spc_transactions(equipment):
    """SPC ledger rows — see equipment.spc for COA Annex A.2 implementation."""
    from .spc import get_spc_transactions as _get_spc_transactions
    return _get_spc_transactions(equipment)


def get_splc_transactions(equipment):
    """SPLC ledger rows — see equipment.splc for COA Annex A.3 implementation."""
    from .splc import get_splc_transactions as _get_splc_transactions
    return _get_splc_transactions(equipment)


def get_rpcsp_data():
    """
    RPCSP reconciliation — semi-expendable records vs physical count.
    Reuses inventory accuracy logic: active (non-retired) items counted.
    """
    from .models import Equipment

    semi_classes = [CLASSIFICATION_SEMI, CLASSIFICATION_LOW]
    items = []
    discrepancies = 0

    qs = Equipment.objects.select_related('category', 'department').exclude(status='Retired')
    for eq in qs:
        update_coa_fields(eq)
        if eq.classification not in semi_classes:
            continue

        recorded_qty = 1
        physical_qty = 1 if eq.status in ('Available', 'Borrowed', 'Maintenance') else 0
        variance = physical_qty - recorded_qty
        if variance != 0:
            discrepancies += 1

        items.append({
            'property_number': eq.property_number,
            'description': eq.display_name,
            'category': eq.category.name if eq.category else '',
            'account_code': eq.coa_account_code,
            'recorded_qty': recorded_qty,
            'physical_qty': physical_qty,
            'variance': variance,
            'amount': effective_cost(eq),
            'status': eq.status,
            'has_discrepancy': variance != 0,
        })

    total = len(items)
    accuracy = round(((total - discrepancies) / max(total, 1)) * 100, 1)
    return {
        'items': items,
        'total': total,
        'discrepancies': discrepancies,
        'accuracy': accuracy,
    }
