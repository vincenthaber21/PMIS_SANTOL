from django.contrib import admin
from .models import BorrowRequest


@admin.register(BorrowRequest)
class BorrowRequestAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'approval_status', 'borrow_date', 'expected_return', 'actual_return')
    list_filter = ('approval_status',)
    search_fields = ('employee__username', 'equipment__name')
