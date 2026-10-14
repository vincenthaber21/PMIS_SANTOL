"""Context processors for PMS."""
from .models import Notification, SiteSettings


def site_settings_processor(request):
    """Inject site branding (name, logo) into all templates."""
    from equipment.inventory_tag import resolve_inventory_tag_representative_name

    site = SiteSettings.get_solo()
    return {
        'site_settings': site,
        'inventory_tag_default_representative_name': resolve_inventory_tag_representative_name(
            site, request,
        ),
    }


def notifications_processor(request):
    """Inject unread notification count and recent notifications into all templates."""
    if request.user.is_authenticated:
        unread = Notification.objects.filter(user=request.user, is_read=False)
        return {
            'unread_notifications': unread[:10],
            'unread_count': unread.count(),
        }
    return {'unread_notifications': [], 'unread_count': 0}
