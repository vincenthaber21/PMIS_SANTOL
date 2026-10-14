"""OTP helpers for verifying user email before account creation."""
import hashlib
import secrets
import string

from django.core.cache import cache
from django.utils import timezone

OTP_LENGTH = 6
OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5
CACHE_PREFIX = 'user_create_otp:'


def _cache_key(token):
    return f'{CACHE_PREFIX}{token}'


def _hash_otp(otp):
    return hashlib.sha256(otp.encode()).hexdigest()


def generate_otp():
    return ''.join(secrets.choice(string.digits) for _ in range(OTP_LENGTH))


def store_pending_registration(admin_id, email, post_data):
    """Store validated registration data and return token + plain OTP."""
    token = secrets.token_urlsafe(32)
    otp = generate_otp()
    payload = {
        'admin_id': admin_id,
        'email': email.lower(),
        'otp_hash': _hash_otp(otp),
        'post_data': post_data,
        'attempts': 0,
        'created_at': timezone.now().isoformat(),
    }
    cache.set(_cache_key(token), payload, OTP_TTL_SECONDS)
    return token, otp


def resend_otp(token):
    """Issue a new OTP for an existing pending registration."""
    payload = cache.get(_cache_key(token))
    if not payload:
        return None, None
    otp = generate_otp()
    payload['otp_hash'] = _hash_otp(otp)
    payload['attempts'] = 0
    cache.set(_cache_key(token), payload, OTP_TTL_SECONDS)
    return payload, otp


def verify_otp(token, otp, admin_id):
    """Verify OTP and return stored post_data when valid."""
    payload = cache.get(_cache_key(token))
    if not payload:
        return None, 'Verification expired. Please send a new code.'

    if payload['admin_id'] != admin_id:
        return None, 'Invalid verification session.'

    payload['attempts'] += 1
    if payload['attempts'] > OTP_MAX_ATTEMPTS:
        cache.delete(_cache_key(token))
        return None, 'Too many failed attempts. Please send a new code.'

    if payload['otp_hash'] != _hash_otp(otp.strip()):
        cache.set(_cache_key(token), payload, OTP_TTL_SECONDS)
        return None, 'Invalid verification code.'

    cache.delete(_cache_key(token))
    return payload['post_data'], None


def mask_email(email):
    """Return a partially masked email for display."""
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + '*'
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]
    return f'{masked_local}@{domain}'
