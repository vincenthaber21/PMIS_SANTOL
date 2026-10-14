from django.contrib import admin
from .models import MaintenanceRequest


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'priority', 'repair_status', 'technician', 'actual_cost', 'date_opened')
    list_filter = ('repair_status', 'priority')
    search_fields = ('equipment__name', 'issue_description')
