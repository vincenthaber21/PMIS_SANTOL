"""Custom User model with role-based access control."""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    PERMISSION_FIELDS = (
        'can_access_site',
        'can_manage_users',
        'can_manage_equipment',
        'can_view_all_equipment',
        'can_manage_borrowing',
        'can_manage_maintenance',
        'can_view_reports',
    )
    DEFAULT_PRESET_BY_NAME = {
        'Admin': 'full',
        'Property Custodian': 'custodian',
        'Supply Officer': 'supply_officer',
        'Technician': 'technician',
        'Employee': 'staff',
    }

    name = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
    )
    can_access_site = models.BooleanField(
        default=True,
        help_text='Allow users with this role to sign in and use the website.',
    )
    can_manage_users = models.BooleanField(
        default=False,
        help_text='User management, role settings, and admin menu.',
    )
    can_manage_equipment = models.BooleanField(
        default=False,
        help_text='Register equipment and manage inventory master data.',
    )
    can_view_all_equipment = models.BooleanField(
        default=False,
        help_text='View the full equipment inventory (not only own items).',
    )
    can_manage_borrowing = models.BooleanField(
        default=False,
        help_text='Approve or reject borrow requests.',
    )
    can_manage_maintenance = models.BooleanField(
        default=False,
        help_text='Update and complete maintenance requests.',
    )
    can_view_reports = models.BooleanField(
        default=False,
        help_text='Reports, COA forms, and audit trail.',
    )
    acts_as_supply_officer = models.BooleanField(
        default=False,
        help_text='Use users with this role as Supply Officer signatories for PAR/ICS forms.',
    )

    def __str__(self):
        return self.name

    @property
    def has_full_access(self):
        return all(getattr(self, field) for field in self.PERMISSION_FIELDS)

    @classmethod
    def preset_for_name(cls, name, fallback=None):
        return cls.DEFAULT_PRESET_BY_NAME.get((name or '').strip(), fallback)

    def apply_preset(self, preset):
        """Apply a named permission preset."""
        full_permissions = {field: True for field in self.PERMISSION_FIELDS}
        presets = {
            'full': {
                **full_permissions,
                'acts_as_supply_officer': False,
            },
            'custodian': {
                **full_permissions,
                'acts_as_supply_officer': True,
            },
            'supply_officer': {
                **full_permissions,
                'acts_as_supply_officer': True,
            },
            'technician': {
                'can_access_site': True,
                'can_manage_users': False,
                'can_manage_equipment': False,
                'can_view_all_equipment': True,
                'can_manage_borrowing': False,
                'can_manage_maintenance': True,
                'can_view_reports': True,
                'acts_as_supply_officer': False,
            },
            'staff': {
                'can_access_site': True,
                'can_manage_users': False,
                'can_manage_equipment': False,
                'can_view_all_equipment': False,
                'can_manage_borrowing': False,
                'can_manage_maintenance': False,
                'can_view_reports': True,
                'acts_as_supply_officer': False,
            },
            'blocked': {
                **{field: False for field in self.PERMISSION_FIELDS},
                'acts_as_supply_officer': False,
            },
        }
        values = presets.get(preset)
        if not values:
            return
        for field, value in values.items():
            setattr(self, field, value)

    def apply_named_default(self, fallback=None):
        preset = self.preset_for_name(self.name, fallback=fallback)
        if preset:
            self.apply_preset(preset)

    class Meta:
        ordering = ['name']
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'


class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.ForeignKey(
        Role, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='users',
    )
    department = models.ForeignKey(
        'equipment.Department', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='members'
    )
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)

    def __str__(self):
        role_name = self.role.name if self.role_id else 'No role'
        return f"{self.get_full_name() or self.username} ({role_name})"

    def _role_active(self):
        return self.role is not None and self.role.status == Role.STATUS_ACTIVE

    def _role_perm(self, field):
        return self._role_active() and getattr(self.role, field, False)

    @property
    def can_access_site(self):
        return self._role_perm('can_access_site')

    @property
    def is_admin(self):
        return self._role_perm('can_manage_users')

    @property
    def is_custodian(self):
        return self._role_perm('can_manage_equipment')

    @property
    def is_supply_officer(self):
        return self._role_active() and getattr(self.role, 'acts_as_supply_officer', False)

    @property
    def is_technician(self):
        return self._role_perm('can_manage_maintenance') and not self._role_perm('can_manage_equipment')

    @property
    def is_employee(self):
        if not self._role_perm('can_access_site'):
            return False
        return not any(
            self._role_perm(field)
            for field in (
                'can_manage_users',
                'can_manage_equipment',
                'can_view_all_equipment',
                'can_manage_borrowing',
                'can_manage_maintenance',
            )
        )

    def can_view_all_equipment(self):
        """Admin, custodian, supply officer, and technician see the full inventory."""
        return self._role_perm('can_view_all_equipment')

    EQUIPMENT_LIST_FULL_ACCESS_ROLES = (
        'Admin', 'Property Custodian', 'Supply Officer', 'Technician',
    )
    DASHBOARD_FULL_ACCESS_ROLES = ('Admin', 'Property Custodian', 'Supply Officer')

    def sees_full_equipment_list(self):
        """Unfiltered equipment list for admin, custodian, supply officer, and technician."""
        if not self._role_active():
            return False
        return self.role.name in self.EQUIPMENT_LIST_FULL_ACCESS_ROLES

    def sees_full_dashboard(self):
        """Admin, Property Custodian, and Supply Officer see organization-wide dashboard data."""
        if not self._role_active():
            return False
        return self.role.name in self.DASHBOARD_FULL_ACCESS_ROLES

    @property
    def can_view_reports_perm(self):
        return self._role_perm('can_view_reports')

    @property
    def can_access_insights(self):
        """Reports, COA forms, and audit trail in the Insights sidebar."""
        return self.is_admin or self.is_custodian or self.is_supply_officer
