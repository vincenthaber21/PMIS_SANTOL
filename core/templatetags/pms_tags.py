"""Custom template tags and filters for PMS."""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def peso(value):
    """Format value as Philippine Peso."""
    try:
        return f"₱{float(value):,.2f}"
    except (TypeError, ValueError):
        return '₱0.00'


@register.filter
def condition_badge(score):
    """Return Bootstrap badge class for condition score."""
    try:
        score = int(score)
        if score >= 70:
            cls = 'success'
            label = 'Good'
        elif score >= 40:
            cls = 'warning'
            label = 'Fair'
        else:
            cls = 'danger'
            label = 'Poor'
        return mark_safe(f'<span class="badge bg-{cls}">{score} – {label}</span>')
    except (TypeError, ValueError):
        return ''


@register.filter
def status_badge(status):
    """Return Bootstrap badge for equipment/request status."""
    colors = {
        'Available': 'success',
        'Borrowed': 'primary',
        'Maintenance': 'warning',
        'Retired': 'secondary',
        'Pending': 'warning',
        'Approved': 'success',
        'Rejected': 'danger',
        'Returned': 'info',
        'Overdue': 'danger',
        'Open': 'danger',
        'In Progress': 'warning',
        'Completed': 'success',
    }
    cls = colors.get(status, 'secondary')
    return mark_safe(f'<span class="badge bg-{cls}">{status}</span>')


@register.filter
def property_status_badge(status):
    """Return a soft-tinted pill for an equipment property status."""
    if not status:
        return mark_safe('<span class="text-muted">—</span>')
    status = str(status)
    variants = {
        'Available': 'success',
        'Working': 'success',
        'Disposed': 'danger',
        'Condemned': 'danger',  # legacy status name
        'Unserviceable': 'warning',
    }
    variant = variants.get(status, 'neutral')
    return mark_safe(f'<span class="badge-soft badge-soft-{variant}">{status}</span>')


@register.filter
def classification_badge(classification):
    """Return Bootstrap badge for COA classification."""
    colors = {
        'PPE': ('primary', 'PPE'),
        'Semi-Expendable': ('info', 'Semi-Expendable'),
        'Low-Value Semi-Expendable': ('secondary', 'Low-Value Semi-Expendable'),
    }
    cls, label = colors.get(classification, ('secondary', classification or 'Unclassified'))
    return mark_safe(f'<span class="badge bg-{cls}">{label}</span>')


@register.filter
def form_type_badge(equipment):
    """Return Bootstrap badge for PAR (PPE) or ICS (semi-expendable)."""
    form_type = getattr(equipment, 'form_type', None)
    if not form_type:
        from equipment.coa import CLASSIFICATION_PPE
        form_type = 'PAR' if getattr(equipment, 'classification', '') == CLASSIFICATION_PPE else 'ICS'
    colors = {
        'PAR': ('primary', 'PAR'),
        'ICS': ('info', 'ICS'),
    }
    cls, label = colors.get(form_type, ('secondary', form_type or '—'))
    title = (
        'Property Acknowledgement Receipt — PPE ≥ ₱50,000'
        if form_type == 'PAR'
        else 'Inventory Custodian Slip — below ₱50,000'
    )
    return mark_safe(f'<span class="badge bg-{cls}" title="{title}">{label}</span>')


@register.filter
def user_office(user):
    """Position/office line for PAR/ICS signature blocks."""
    if not user:
        return ''
    from core.signatories import end_user_position
    return end_user_position(user)


@register.filter
def priority_badge(priority):
    colors = {
        'Low': 'info',
        'Medium': 'warning',
        'High': 'danger',
        'Critical': 'dark',
    }
    cls = colors.get(priority, 'secondary')
    return mark_safe(f'<span class="badge bg-{cls}">{priority}</span>')
