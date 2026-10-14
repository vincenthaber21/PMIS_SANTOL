"""Signals for equipment app — audit logging and COA side effects."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Equipment, EquipmentAssignmentHistory, user_display_name


def record_assignment_change(equipment, old_user, changed_by=None):
    """Create a history row when the assigned user changes."""
    new_user = equipment.assigned_user
    if new_user:
        notes = 'Reassigned' if old_user else 'Assigned'
    else:
        notes = 'Unassigned'
    EquipmentAssignmentHistory.objects.create(
        equipment=equipment,
        user=new_user,
        user_name=user_display_name(new_user),
        previous_user_name=user_display_name(old_user) if old_user else '',
        changed_by=changed_by,
        notes=notes,
    )


@receiver(pre_save, sender=Equipment)
def equipment_pre_save(sender, instance, raw=False, **kwargs):
    """Store original status, assignee, and detail fields for change detection."""
    # loaddata / fixtures use raw=True — skip side-effect bookkeeping.
    if raw:
        return
    if instance.pk:
        try:
            original = Equipment.objects.get(pk=instance.pk)
            instance._original_status = original.status
            instance._original_assigned_user = original.assigned_user
            from .notifications import capture_detail_snapshot
            instance._original_detail_snapshot = capture_detail_snapshot(original)
        except Equipment.DoesNotExist:
            instance._original_status = None
            instance._original_assigned_user = None
            instance._original_detail_snapshot = None
    else:
        instance._original_status = None
        instance._original_assigned_user = None
        instance._original_detail_snapshot = None


@receiver(post_save, sender=Equipment)
def equipment_post_save(sender, instance, created, raw=False, **kwargs):
    """Log equipment create/update actions, assignment changes, and COA entries."""
    # Import must not auto-create PAR/ICS/COA — fixtures already include them.
    if raw:
        return

    from core.models import AuditLog
    from .coa import (
        create_acquisition_entry,
        create_reclassification_entry,
        process_issuance,
    )

    action = 'CREATE' if created else 'UPDATE'
    AuditLog.objects.create(
        user=None,
        action=action,
        model_name='Equipment',
        object_id=instance.pk,
        details=f'Equipment {instance.property_number} ({instance.name}) {action.lower()}d. Status: {instance.status}'
    )

    old_user = getattr(instance, '_original_assigned_user', None)
    new_user = instance.assigned_user
    changed_by = getattr(instance, '_assignment_changed_by', None)
    assignment_just_changed = False

    if created:
        if new_user:
            record_assignment_change(instance, old_user=None, changed_by=changed_by)
            assignment_just_changed = True
            from .notifications import notify_assigned_user
            notify_assigned_user(instance, action='assigned')
    elif (old_user or None) != (new_user or None):
        record_assignment_change(instance, old_user=old_user, changed_by=changed_by)
        assignment_just_changed = True
        if new_user:
            from .notifications import notify_assigned_user
            notify_assigned_user(instance, action='reassigned')

    # COA: acquisition JEV on first save
    if getattr(instance, '_coa_is_new', False):
        create_acquisition_entry(instance, created_by=changed_by)
        from .ics import create_ics_for_equipment
        from .par import create_par_for_equipment
        create_ics_for_equipment(instance, created_by=changed_by)
        create_par_for_equipment(instance, created_by=changed_by)

    # COA: reclassification JEV when classification changes
    old_classification = getattr(instance, '_coa_old_classification', None)
    if old_classification and old_classification != instance.classification:
        create_reclassification_entry(instance, old_classification, created_by=changed_by)

    # COA: issuance on first assignment only (PAR for PPE, ICS + expense entry for semi-expendable)
    if assignment_just_changed and new_user and old_user is None:
        history = instance.assignment_history.order_by('-assigned_at').first()
        process_issuance(
            instance,
            end_user=new_user,
            custodian=changed_by,
            reference_type='EquipmentAssignmentHistory',
            reference_id=history.pk if history else None,
            created_by=changed_by,
        )

    if not created:
        from .notifications import (
            capture_detail_snapshot,
            diff_detail_snapshots,
            notify_equipment_details_updated,
        )

        before = getattr(instance, '_original_detail_snapshot', None)
        if before is not None:
            after = capture_detail_snapshot(instance)
            changes = diff_detail_snapshots(before, after)
            skip_assigned_user = assignment_just_changed and bool(new_user)
            notify_equipment_details_updated(
                instance,
                changes,
                updated_by=changed_by,
                skip_assigned_user=skip_assigned_user,
            )
