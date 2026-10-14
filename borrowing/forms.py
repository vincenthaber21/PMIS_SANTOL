"""Forms for borrowing app."""
from django import forms
from django.utils import timezone
from .models import BorrowRequest
from equipment.models import Equipment


class BorrowRequestForm(forms.ModelForm):
    class Meta:
        model = BorrowRequest
        fields = ('equipment', 'quantity', 'purpose', 'borrow_date', 'expected_return')
        widgets = {
            'borrow_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'expected_return': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'purpose': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['equipment'].queryset = Equipment.objects.filter(status='Available')
        for name, field in self.fields.items():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'form-control'

    def clean(self):
        cleaned = super().clean()
        borrow = cleaned.get('borrow_date')
        ret = cleaned.get('expected_return')
        if borrow and ret and ret <= borrow:
            raise forms.ValidationError('Expected return date must be after borrow date.')
        return cleaned


class ApprovalForm(forms.Form):
    action = forms.ChoiceField(choices=[('Approved', 'Approve'), ('Rejected', 'Reject')])
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['action'].widget.attrs['class'] = 'form-select'
