"""Email helpers for equipment notifications."""
import logging
import os

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from core.models import SiteSettings

logger = logging.getLogger(__name__)


def _site_base_url():
    return os.environ.get('SITE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')


def equipment_detail_url(equipment):
    path = reverse('equipment:detail', args=[equipment.pk])
    return f'{_site_base_url()}{path}'


def _send_email(user, subject, text_template, html_template, context):
    if not user or not user.email:
        return False

    site = SiteSettings.get_solo()
    email_context = {
        'user': user,
        'site_name': site.site_full_name,
        'site_short_name': site.site_short_name,
        **context,
    }
    text_body = render_to_string(text_template, email_context)
    html_body = render_to_string(html_template, email_context)

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        message.attach_alternative(html_body, 'text/html')
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Failed to send equipment email to %s', user.email)
        return False


def send_equipment_update_email(user, equipment, changes, updated_by=None):
    """Email admins or assigned users when equipment details change."""
    site = SiteSettings.get_solo()
    subject = (
        f'Equipment updated: {equipment.name} ({equipment.property_number})'
        f' — {site.site_short_name}'
    )
    return _send_email(
        user,
        subject,
        'equipment/email/equipment_updated.txt',
        'equipment/email/equipment_updated.html',
        {
            'equipment': equipment,
            'changes': changes,
            'updated_by': updated_by,
            'equipment_url': equipment_detail_url(equipment),
        },
    )


def send_equipment_assignment_email(user, equipment, *, action='assigned'):
    """Email the assigned user with full property details."""
    site = SiteSettings.get_solo()
    action_label = 'assigned to you' if action == 'assigned' else 'reassigned to you'
    subject = (
        f'Property {action_label}: {equipment.name} ({equipment.property_number})'
        f' — {site.site_short_name}'
    )
    from .notifications import build_equipment_assignment_message

    return _send_email(
        user,
        subject,
        'equipment/email/equipment_assigned.txt',
        'equipment/email/equipment_assigned.html',
        {
            'equipment': equipment,
            'action': action,
            'action_label': action_label,
            'details_text': build_equipment_assignment_message(equipment, action=action),
            'equipment_url': equipment_detail_url(equipment),
        },
    )
