"""Lazy admin branding from SiteSettings — avoids DB access during app init."""
import types

from django.contrib import admin
from django.contrib.admin.sites import AdminSite

DEFAULT_BRANDING = {
    'site_header': 'PMS Administration',
    'site_title': 'PMS Admin',
    'index_title': 'Property Management System',
}

_branding_cache = None


def invalidate_admin_branding_cache():
    global _branding_cache
    _branding_cache = None


def get_admin_branding():
    global _branding_cache
    if _branding_cache is not None:
        return _branding_cache

    from django.db.utils import OperationalError, ProgrammingError

    try:
        from .models import SiteSettings

        settings_obj = SiteSettings.get_solo()
        _branding_cache = {
            'site_header': f'{settings_obj.site_short_name} Administration',
            'site_title': settings_obj.site_short_name,
            'index_title': settings_obj.site_full_name,
        }
    except (OperationalError, ProgrammingError):
        _branding_cache = DEFAULT_BRANDING.copy()

    return _branding_cache


def apply_admin_branding():
    branding = get_admin_branding()
    admin.site.site_header = branding['site_header']
    admin.site.site_title = branding['site_title']
    admin.site.index_title = branding['index_title']
    return branding


def patch_admin_branding():
    """Load SiteSettings branding on first admin request, not at startup."""
    if getattr(admin.site, '_pms_branding_patched', False):
        return

    original_each_context = AdminSite.each_context

    def each_context(self, request):
        context = original_each_context(self, request)
        branding = apply_admin_branding()
        context.update(branding)
        return context

    admin.site.each_context = types.MethodType(each_context, admin.site)
    admin.site._pms_branding_patched = True
