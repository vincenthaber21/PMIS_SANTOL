"""In-app notifications for equipment assignment and detail updates."""
from core.models import Notification

DETAIL_FIELD_LABELS = {
    'name': 'Article/Item Name',
    'category_id': 'Category',
    'serial_number': 'Serial Number',
    'property_status_id': 'Property Status',
    'disposal_reason_id': 'Disposal Reason',
    'department_id': 'Location',
    'assigned_user_id': 'Assigned User',
    'supplier_id': 'Supplier',
    'mode_of_procurement_id': 'Mode of Procurement',
    'quantity': 'Quantity',
    'unit': 'Unit',
    'fund_source_id': 'Fund Source',
    'description': 'Description',
    'acquisition_cost': 'Unit Value',
    'purchase_date': 'Date Acquired',
    'estimated_useful_life': 'Useful Life (years)',
}

DETAIL_TRACKED_FIELDS = tuple(DETAIL_FIELD_LABELS.keys())


def _format_value(value):
    if value is None:
        return ''
    text = str(value).strip()
    return '' if not text or text == '—' else text


def build_equipment_assignment_message(equipment, *, action='assigned'):
    """Build a detailed notification message with all property information."""
    from .models import Equipment

    equipment = Equipment.objects.select_related(
        'category', 'department', 'property_status', 'disposal_reason', 'fund_source',
        'mode_of_procurement', 'supplier', 'assigned_user',
    ).get(pk=equipment.pk)

    verb = 'assigned' if action == 'assigned' else 'reassigned to'
    lines = [
        f'You have been {verb} the following property: {equipment.name} ({equipment.property_number}).',
        '',
        'Property Information:',
    ]

    def add(label, value):
        formatted = _format_value(value)
        if formatted:
            lines.append(f'• {label}: {formatted}')

    for label, value in equipment.get_qr_label_fields():
        add(label, value)

    add('Description', equipment.description)
    add('Office / Department', equipment.department)
    add('Quantity / Unit', f'{equipment.quantity} {equipment.unit}')
    add('P.O. Number', equipment.purchase_order_no)
    if equipment.payment_method:
        add('Payment Method', str(equipment.payment_method))
    if equipment.warranty_until:
        add('Warranty Until', equipment.warranty_until.strftime('%Y-%m-%d'))
    add('Estimated Useful Life', f'{equipment.estimated_useful_life} years')

    return '\n'.join(lines)


def notify_assigned_user(equipment, *, action='assigned'):
    """Notify the assigned user with full property details."""
    user = equipment.assigned_user
    if not user:
        return

    Notification.objects.create(
        user=user,
        message=build_equipment_assignment_message(equipment, action=action),
        type='info',
    )
    from .emails import send_equipment_assignment_email
    send_equipment_assignment_email(user, equipment, action=action)


def _detail_field_display(equipment, field_name):
    """Return a human-readable value for a tracked equipment detail field."""
    from .models import user_display_name

    if field_name == 'assigned_user_id':
        return user_display_name(equipment.assigned_user) if equipment.assigned_user_id else 'Unassigned'
    if field_name == 'category_id':
        return str(equipment.category) if equipment.category_id else '—'
    if field_name == 'property_status_id':
        return str(equipment.property_status) if equipment.property_status_id else '—'
    if field_name == 'disposal_reason_id':
        return str(equipment.disposal_reason) if equipment.disposal_reason_id else '—'
    if field_name == 'department_id':
        return equipment.display_location
    if field_name == 'supplier_id':
        return str(equipment.supplier) if equipment.supplier_id else '—'
    if field_name == 'mode_of_procurement_id':
        return str(equipment.mode_of_procurement) if equipment.mode_of_procurement_id else '—'
    if field_name == 'fund_source_id':
        if equipment.fund_source_id:
            return str(equipment.fund_source)
        return equipment.fund or '—'
    if field_name == 'acquisition_cost':
        if equipment.acquisition_cost:
            return f'₱{equipment.acquisition_cost:,.2f}'
        return '—'
    if field_name == 'purchase_date':
        return equipment.purchase_date.strftime('%Y-%m-%d') if equipment.purchase_date else '—'
    if field_name == 'estimated_useful_life':
        return str(equipment.estimated_useful_life or '—')
    if field_name == 'quantity':
        return str(equipment.quantity)
    value = getattr(equipment, field_name, None)
    formatted = _format_value(value)
    return formatted or '—'


def capture_detail_snapshot(equipment):
    """Snapshot tracked detail fields for change detection."""
    return {
        field_name: _detail_field_display(equipment, field_name)
        for field_name in DETAIL_TRACKED_FIELDS
    }


def diff_detail_snapshots(before, after):
    """Return list of (label, old_value, new_value) for changed detail fields."""
    changes = []
    for field_name in DETAIL_TRACKED_FIELDS:
        old_value = before.get(field_name, '—')
        new_value = after.get(field_name, '—')
        if old_value != new_value:
            changes.append((DETAIL_FIELD_LABELS[field_name], old_value, new_value))
    return changes


def build_equipment_update_message(equipment, changes, updated_by=None):
    """Build a notification message listing equipment detail changes."""
    lines = [
        f'Equipment details updated for {equipment.name} ({equipment.property_number}).',
        '',
        'Changes:',
    ]
    for label, old_value, new_value in changes:
        lines.append(f'• {label}: {old_value} → {new_value}')
    if updated_by:
        lines.append('')
        lines.append(f'Updated by: {updated_by.get_full_name() or updated_by.username}')
    return '\n'.join(lines)


def get_admin_users():
    """Active users with admin privileges."""
    from accounts.models import User

    return User.objects.filter(
        role__can_manage_users=True,
        role__status='Active',
        is_active=True,
    )


def notify_equipment_details_updated(
    equipment,
    changes,
    *,
    updated_by=None,
    skip_assigned_user=False,
):
    """Notify admins and the assigned user when equipment details change."""
    if not changes:
        return

    message = build_equipment_update_message(equipment, changes, updated_by=updated_by)
    notified_user_ids = set()

    if updated_by:
        notified_user_ids.add(updated_by.pk)

    assigned_user = equipment.assigned_user
    # Assignment already sends a dedicated notification/email; skip the update
    # duplicate for the assignee (including when they are also an admin).
    if skip_assigned_user and assigned_user:
        notified_user_ids.add(assigned_user.pk)

    from .emails import send_equipment_update_email

    for admin in get_admin_users():
        if admin.pk in notified_user_ids:
            continue
        Notification.objects.create(user=admin, message=message, type='info')
        send_equipment_update_email(admin, equipment, changes, updated_by=updated_by)
        notified_user_ids.add(admin.pk)

    if (
        assigned_user
        and not skip_assigned_user
        and assigned_user.pk not in notified_user_ids
    ):
        Notification.objects.create(user=assigned_user, message=message, type='info')
        send_equipment_update_email(
            assigned_user, equipment, changes, updated_by=updated_by,
        )
