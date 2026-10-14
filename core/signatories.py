"""Shared helpers for PAR/ICS signature blocks."""
from accounts.models import Role, User

SUPPLY_OFFICER_LABEL = 'Supply Officer'


def par_issued_by_position():
    """Position/office line for PAR “Issued by” — always Supply Officer (Appendix 71)."""
    return SUPPLY_OFFICER_LABEL


def supply_officer_users():
    """Active users whose role is marked as a supply-officer signatory."""
    return (
        User.objects.filter(
            role__status=Role.STATUS_ACTIVE,
            role__acts_as_supply_officer=True,
            is_active=True,
        )
        .select_related('role', 'department')
        .order_by('first_name', 'last_name', 'username')
    )


def default_supply_officer_user():
    """Fallback user for supply-officer signature blocks."""
    return (
        supply_officer_users().first()
        or User.objects.filter(is_active=True).first()
    )


def active_supply_officer_user(*, officer_id=None, user=None):
    """
    Return a user who is an active supply officer in the database.

    Used for PAR/ICS “Issued by” blocks so the printed name always reflects
    role data, not the logged-in user or a stale PAR custodian.
    """
    qs = supply_officer_users()
    if officer_id is not None:
        try:
            return qs.get(pk=int(officer_id))
        except (TypeError, ValueError, User.DoesNotExist):
            pass
    if user is not None and qs.filter(pk=user.pk).exists():
        return user
    return default_supply_officer_user()


def supply_officer_choices():
    """
    Users selectable as the PAR/ICS 'Received from' signatory.

    Falls back to every active user when no role is flagged as a supply
    officer yet, so the download picker is never empty and PAR downloads
    stay available to all users regardless of role setup.
    """
    officers = list(supply_officer_users())
    if officers:
        return officers
    return list(
        User.objects.filter(is_active=True)
        .select_related('role', 'department')
        .order_by('first_name', 'last_name', 'username')
    )


def is_supply_officer(user):
    """True when the user has supply-officer role behavior enabled."""
    return bool(user and getattr(user, 'is_supply_officer', False))


def admin_must_pick_supply_officer(user):
    """Admins choose the issuing supply officer; supply officers use themselves."""
    return bool(user and user.is_authenticated and user.is_admin and not is_supply_officer(user))


def build_par_signatory_overrides(received_by_name, received_by_position, supply_officer):
    """Explicit PAR signature block values from the pre-download form."""
    return {
        'received_by_name': received_by_name,
        'received_by_position': received_by_position,
        'received_from_name': supply_officer.get_full_name() if supply_officer else '',
        'received_from_position': par_issued_by_position(),
    }


def parse_par_export_signature(request, end_user=None, **_kwargs):
    """
    Read PAR signature fields from optional GET params.
    “Received by” defaults to the equipment assignee (end_user), never the
    logged-in user. Returns (overrides, supply_officer).
    """
    received_by_name = (request.GET.get('received_by_name') or '').strip()
    received_by_position = (request.GET.get('received_by_position') or '').strip()

    resolved_end_user = end_user or resolve_par_received_by_user()
    if not received_by_name and resolved_end_user:
        received_by_name = resolved_end_user.get_full_name() or resolved_end_user.username
    if not received_by_position and resolved_end_user:
        received_by_position = end_user_position(resolved_end_user)

    supply_officer = resolve_par_download_supply_officer(
        request.user,
        request.GET.get('supply_officer'),
    )

    overrides = build_par_signatory_overrides(
        received_by_name, received_by_position, supply_officer,
    )
    return overrides, supply_officer


def resolve_supply_officer(custodian=None):
    """Active supply officer from the database (not a stored PAR custodian)."""
    if custodian and supply_officer_users().filter(pk=custodian.pk).exists():
        return custodian
    return default_supply_officer_user()


def resolve_par_download_supply_officer(request_user, officer_id=None):
    """
    Resolve the supply officer for a PAR PDF download.

    Always reads from users with an active supply-officer role in the
    database. An optional officer_id must match that set; the logged-in
    user is never assumed to be the issuer.
    """
    return active_supply_officer_user(officer_id=officer_id)


def supply_officer_position(user, *, include_department=False):
    """Position/office line for supply officer signature blocks."""
    if user and include_department and getattr(user, 'department', None):
        return f'{SUPPLY_OFFICER_LABEL}, {user.department.name}'
    return SUPPLY_OFFICER_LABEL


def end_user_position(user):
    """Position/office line for end-user / received-by signature blocks."""
    if not user:
        return ''
    if getattr(user, 'department', None):
        return user.department.name
    return user.role.name if user.role_id else ''


def resolve_par_received_by_user(
    *,
    end_user=None,
    equipment=None,
    equipment_list=None,
    par=None,
    personnel_id=None,
):
    """Pick the end-user for PAR “Received by” — equipment assignee, not the logged-in user."""
    if par is not None:
        item = (
            par.items
            .select_related(
                'equipment__assigned_user__role',
                'equipment__assigned_user__department',
            )
            .first()
        )
        if item and item.equipment.assigned_user_id:
            return item.equipment.assigned_user
        if par.end_user_id:
            return par.end_user
    if equipment is not None and equipment.assigned_user_id:
        return equipment.assigned_user
    if personnel_id:
        try:
            return User.objects.get(pk=int(personnel_id), is_active=True)
        except (TypeError, ValueError, User.DoesNotExist):
            pass
    if equipment_list:
        assignees = [
            eq.assigned_user
            for eq in equipment_list
            if getattr(eq, 'assigned_user_id', None)
        ]
        unique_ids = {user.pk for user in assignees}
        if len(unique_ids) == 1:
            return assignees[0]
    if end_user is not None:
        return end_user
    return None
