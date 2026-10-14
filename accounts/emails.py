"""Email helpers for account notifications."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from core.models import SiteSettings

logger = logging.getLogger(__name__)


def send_account_created_email(user, password, login_url):
    """Email new users their account details after an admin creates their account."""
    if not user.email:
        return False

    site = SiteSettings.get_solo()
    context = {
        'user': user,
        'password': password,
        'login_url': login_url,
        'site_name': site.site_full_name,
        'site_short_name': site.site_short_name,
    }
    subject = f'Your {site.site_short_name} account has been created'
    text_body = render_to_string('accounts/email/account_created.txt', context)
    html_body = render_to_string('accounts/email/account_created.html', context)

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
        logger.exception('Failed to send account email to %s', user.email)
        return False


def send_user_creation_otp_email(email, otp, expires_minutes=10):
    """Send a one-time verification code to confirm the user's email address."""
    site = SiteSettings.get_solo()
    context = {
        'otp': otp,
        'expires_minutes': expires_minutes,
        'site_name': site.site_full_name,
        'site_short_name': site.site_short_name,
    }
    subject = f'Verify your email — {site.site_short_name} account setup'
    text_body = render_to_string('accounts/email/user_otp.txt', context)
    html_body = render_to_string('accounts/email/user_otp.html', context)

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        message.attach_alternative(html_body, 'text/html')
        message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Failed to send OTP email to %s', email)
        return False
