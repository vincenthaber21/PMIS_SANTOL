from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'status', 'access_summary', 'can_access_site',
        'can_manage_users', 'can_manage_equipment', 'can_view_all_equipment',
        'can_manage_borrowing', 'can_manage_maintenance', 'can_view_reports',
        'acts_as_supply_officer',
        'user_count',
    )
    list_display_links = ('name',)
    list_editable = (
        'can_access_site', 'can_manage_users', 'can_manage_equipment',
        'can_view_all_equipment', 'can_manage_borrowing', 'can_manage_maintenance',
        'can_view_reports', 'acts_as_supply_officer',
    )
    list_filter = ('status', 'can_access_site', 'can_manage_users', 'acts_as_supply_officer')
    search_fields = ('name',)
    fieldsets = (
        (None, {'fields': ('name', 'status')}),
        ('Website access permissions', {
            'fields': Role.PERMISSION_FIELDS + ('acts_as_supply_officer',),
            'description': (
                'Use the quick preset buttons below, or tick each permission manually. '
                'Users without <strong>Can access site</strong> cannot sign in. '
                'Turn on <strong>Acts as supply officer</strong> for PAR/ICS signatories.'
            ),
        }),
    )
    change_form_template = 'admin/accounts/role/change_form.html'
    change_list_template = 'admin/accounts/role/change_list.html'

    @admin.display(description='Access')
    def access_summary(self, obj):
        if not obj.can_access_site:
            return format_html('<span style="color:#b91c1c;font-weight:600;">No access</span>')
        if obj.has_full_access:
            return format_html('<span style="color:#15803d;font-weight:600;">Full website</span>')
        return format_html('<span style="color:#b45309;font-weight:600;">Partial</span>')

    @admin.display(description='Users')
    def user_count(self, obj):
        return obj.users.count()


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'department')
    list_filter = ('role', 'department', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    fieldsets = UserAdmin.fieldsets + (
        ('Role & Department', {'fields': ('role', 'department', 'phone', 'avatar')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role & Department', {'fields': ('role', 'department', 'phone')}),
    )
