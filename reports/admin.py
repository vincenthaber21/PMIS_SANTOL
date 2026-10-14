from django.contrib import admin

from .models import ParExportSignatory


@admin.register(ParExportSignatory)
class ParExportSignatoryAdmin(admin.ModelAdmin):
    list_display = (
        'exported_at',
        'signature_over_printed_name',
        'position_office',
        'supply_officer',
        'exported_by',
        'report_type',
        'item_count',
    )
    list_filter = ('report_type', 'exported_at')
    search_fields = (
        'signature_over_printed_name',
        'position_office',
        'supply_officer__first_name',
        'supply_officer__last_name',
    )
    readonly_fields = ('exported_at',)
    date_hierarchy = 'exported_at'
