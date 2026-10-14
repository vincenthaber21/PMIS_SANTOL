"""Forms for accounts app."""
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, PasswordChangeForm
from .models import Role, User


class LoginForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your username',
        'autocomplete': 'username',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your password',
        'autocomplete': 'current-password',
    }))


class UserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'role', 'department', 'phone', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self.fields['role'].queryset = Role.objects.filter(status=Role.STATUS_ACTIVE)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class UserEditForm(UserChangeForm):
    password = None

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'role', 'department', 'phone', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self.fields['role'].queryset = Role.objects.filter(status=Role.STATUS_ACTIVE)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ('name', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Supervisor',
            'maxlength': '50',
        })
        self.fields['status'].widget.attrs['class'] = 'form-select'


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone', 'avatar')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class ProfilePasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            'old_password': 'Enter current password',
            'new_password1': 'Enter new password',
            'new_password2': 'Confirm new password',
        }
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'
            field.widget.attrs['placeholder'] = placeholders.get(name, '')
            field.widget.attrs['autocomplete'] = (
                'current-password' if name == 'old_password' else 'new-password'
            )
