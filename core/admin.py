from django.contrib import admin
from django.urls import reverse

from .admin_branding import patch_admin_branding
from .admin_export import get_download_admin_urls
from .models import (
    AuditLog,
    AutoDatabaseDownloadSchedule,
    DatabaseDownload,
    Notification,
    QuarterlyDatabaseBackup,
    SiteSettings,
)

# Custom admin home with Database Export panel
admin.site.index_template = 'admin/pms_index.html'
admin.site.site_header = 'PMS Administration'
admin.site.site_title = 'PMS Admin'
admin.site.index_title = 'Property Management System'


def _patch_admin_urls():
    """Register /admin/download-database/ without replacing AdminSite."""
    if getattr(admin.site, '_pms_download_urls_patched', False):
        return
    _original_get_urls = admin.site.get_urls

    def get_urls():
        return get_download_admin_urls() + _original_get_urls()

    admin.site.get_urls = get_urls
    admin.site._pms_download_urls_patched = True


_patch_admin_urls()
patch_admin_branding()


@admin.register(AutoDatabaseDownloadSchedule)
class AutoDatabaseDownloadScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'is_enabled',
        'countdown_days',
        'start_date',
        'last_run_at',
        'updated_at',
    )
    readonly_fields = ('last_run_at', 'last_download', 'updated_by', 'updated_at')

    def has_add_permission(self, request):
        return not AutoDatabaseDownloadSchedule.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DatabaseDownload)
class DatabaseDownloadAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'filename',
        'year',
        'quarter',
        'export_format',
        'file_size',
        'object_count',
        'created_by',
    )
    list_filter = ('export_format', 'year', 'quarter', 'created_at')
    search_fields = ('filename', 'notes')
    readonly_fields = (
        'filename',
        'export_format',
        'file',
        'file_size',
        'object_count',
        'year',
        'quarter',
        'created_by',
        'created_at',
        'notes',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(QuarterlyDatabaseBackup)
class QuarterlyDatabaseBackupAdmin(admin.ModelAdmin):
    list_display = (
        'year',
        'quarter',
        'created_at',
        'created_by',
        'download',
        'notes',
    )
    list_filter = ('year', 'quarter')
    search_fields = ('notes',)
    readonly_fields = ('download', 'created_by', 'created_at')
    ordering = ('-year', '-quarter', '-created_at')

    def has_add_permission(self, request):
        # Create via /admin/download-database/ form (triggers ZIP download).
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'model_name', 'object_id')
    list_filter = ('action', 'model_name')
    readonly_fields = ('timestamp',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'is_read', 'created_at', 'message')
    list_filter = ('type', 'is_read')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    change_form_template = 'admin/core/sitesettings/change_form.html'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        if request.user.is_superuser:
            extra_context['download_database_url'] = reverse(
                'admin:download_database'
            )
        return super().change_view(
            request, object_id, form_url, extra_context=extra_context
        )

    fieldsets = (
        ('Branding', {
            'fields': ('site_short_name', 'site_full_name', 'tagline'),
        }),
        ('Logo', {
            'fields': ('logo', 'logo_letter'),
            'description': 'Upload a logo image or set a letter to display when no image is set.',
        }),
        ('Property Number', {
            'fields': (
                'property_number_unique_per_unit',
                'property_number_use_legacy_lgu_code',
                'property_number_lgu_code',
            ),
            'description': (
                '<strong>Unique property number per unit</strong> controls quantity. '
                'Enabled: 10 units are saved as 10 records with consecutive numbers. '
                'Disabled: 10 units are saved as one record that shares a single property number. '
                'When legacy mode is <strong>disabled</strong>, new property numbers use '
                'year–category–item count–department (e.g. <code>2027-05-01-001-HRMO</code>). '
                'When <strong>enabled</strong>, they start with the LGU code below '
                '(e.g. <code>LGU-SANTOL-201-2027-PR-0001</code> or <code>0621-201-2027-PR-0001</code>). '
                'The PAR Header municipality is not used in the property number. '
                'The LGU code is always printed on inventory tags.'
            ),
        }),
        ('PAR Header (Appendix 71)', {
            'fields': ('par_header_title', 'lgu_municipality', 'lgu_province'),
            'description': (
                'Three-line header box printed on every Property Acknowledgement Receipt — '
                'title, municipality, and province (e.g. PROPERTY ACKNOWLEDGEMENT RECEIPT / '
                'MUNICIPALITY OF SUDIPEN / PROVINCE OF LA UNION).'
            ),
        }),
        ('PAR Signatories', {
            'fields': (
                'par_use_site_signatories',
                'par_received_by_name',
                'par_received_by_position',
                'par_received_from_name',
                'par_received_from_position',
            ),
            'description': (
                'Default signatories printed on every Property Acknowledgment Receipt (PAR, Appendix 71). '
                '“Received by” is the end-user; “Issued by” is the supply and/or property custodian. '
                'Enable “Use site default signatories” to print the names below on every PAR; '
                'leave disabled to use each PAR’s assigned users instead. '
                '“Issued by” always defaults to the Property Custodian / Supply Officer.'
            ),
        }),
        ('ICS Signatories', {
            'fields': (
                'ics_received_by_name',
                'ics_received_by_position',
                'ics_received_from_name',
                'ics_received_from_position',
            ),
            'description': (
                'Two signatories printed on every Inventory Custodian Slip (ICS, Appendix 59). '
                '“Received by” is the custodian/end-user; “Received from” is the supply officer.'
            ),
        }),
        ('ICS Supplier Block', {
            'fields': (
                'ics_supplier_address',
                'ics_po_number',
                'ics_header_date',
                'ics_mode_of_procurement',
            ),
            'description': (
                'Default Address, P.O. #, Date, and MOP shown on every ICS header. '
                'Supplier name is set per equipment / ICS record, not here.'
            ),
        }),
        ('PPE Ledger Card (Appendix 70)', {
            'fields': (
                'ppe_depreciable_percent',
                'ppe_prepared_by_name',
                'ppe_prepared_by_position',
                'ppe_noted_by_name',
                'ppe_noted_by_position',
            ),
            'description': (
                'Property, Plant and Equipment Ledger Card. '
                'Depreciable value is the percent of acquisition cost that is depreciated '
                '(95 leaves a 5% residual). Annual depreciation is that amount divided by '
                'useful life. A purchase on days 1–15 starts depreciation in the purchase month; '
                'day 16 or later starts on the first day of the next month. '
                'The first and last years are prorated by month. '
                'Completed maintenance records print in the Repair History columns.'
            ),
        }),
        ('Inventory Tag Defaults', {
            'fields': (
                'inventory_tag_date_counted',
                'inventory_tag_coa_representative',
            ),
            'description': (
                'Default values used in the inventory tag print form before printing. '
                'Users can still adjust Date:(Counted) and COA Representative per print.'
            ),
        }),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
