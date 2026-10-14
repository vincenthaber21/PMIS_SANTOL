"""Forms for maintenance app."""
from django import forms
from accounts.models import Role, User

from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ('equipment', 'issue_description', 'priority', 'estimated_cost')
        widgets = {
            'issue_description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'form-control'


class MaintenanceUpdateForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ('technician', 'repair_status', 'actual_cost', 'completion_date', 'technician_notes')
        widgets = {
            'completion_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'technician_notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['technician'].queryset = User.objects.filter(
            role__status=Role.STATUS_ACTIVE,
            role__can_manage_maintenance=True,
            role__can_manage_equipment=False,
            is_active=True,
        ).select_related('role').order_by('first_name', 'last_name', 'username')
        for name, field in self.fields.items():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'form-control'
