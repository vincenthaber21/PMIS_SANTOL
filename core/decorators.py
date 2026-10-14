"""Access decorators for role-gated views."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def insights_login_required(view_func):
    """Restrict view to Admin, Property Custodian, or Supply Officer."""

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_admin or user.is_custodian or user.is_supply_officer):
            messages.error(
                request,
                'Access denied. Insights are limited to Admin, Property Custodian, '
                'or Supply Officer.',
            )
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def reports_login_required(view_func):
    """Restrict view to users with report access."""

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.can_view_reports_perm:
            messages.error(request, 'Access denied. Report access is required.')
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper
