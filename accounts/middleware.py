"""Middleware for role-based website access."""
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class RoleAccessMiddleware:
    """Log out users whose role no longer has website access."""

    EXEMPT_PREFIXES = (
        '/accounts/login',
        '/accounts/logout',
        '/admin/',
        '/static/',
        '/media/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_superuser:
            if not user.can_access_site and not self._is_exempt(request.path):
                logout(request)
                messages.error(
                    request,
                    'Your account role does not have website access. Contact an administrator.',
                )
                return redirect('accounts:login')
        return self.get_response(request)

    def _is_exempt(self, path):
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)
