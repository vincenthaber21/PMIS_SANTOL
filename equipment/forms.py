"""Forms for equipment app."""
from django import forms
from django.db.models import Q
from accounts.models import User
from .models import (
    Equipment, Department, Category, EquipmentItem, PropertyStatus, FundSource, ModeOfProcurement,
    PaymentMethod, DisposalReason, Supplier,
    normalize_equipment_name,
)
from .coa import (
    CLASSIFICATION_CHOICES,
    CLASSIFICATION_LOW,
    CLASSIFICATION_PPE,
    CLASSIFICATION_SEMI,
)
from .property_number import generate_property_number, preview_property_number

USEFUL_LIFE_CHOICES = [('', 'Select Useful Life')] + [
    (year, f'{year} year{"s" if year != 1 else ""}')
    for year in range(1, 51)
]

_CLASSIFICATION_FILTER_ORDER = (
    CLASSIFICATION_PPE,
    CLASSIFICATION_SEMI,
    CLASSIFICATION_LOW,
)
_CLASSIFICATION_FORM_HINT = {
    CLASSIFICATION_PPE: 'PAR',
    CLASSIFICATION_SEMI: 'ICS',
    CLASSIFICATION_LOW: 'ICS',
}

_CREATE_REQUIRED_FIELDS = (
    'name', 'quantity', 'unit', 'acquisition_cost', 'purchase_date',
    'fund_source', 'category', 'department',
)


def _coerce_useful_life(value):
    if value in (None, ''):
        return None
    return int(value)


class AssignUserForm(forms.Form):
    assigned_user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username'),
        required=False,
        empty_label='Unassigned',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class UpdatePropertyStatusForm(forms.Form):
    property_status = forms.ModelChoiceField(
        queryset=PropertyStatus.objects.filter(status=PropertyStatus.STATUS_ACTIVE).order_by('name'),
        required=False,
        empty_label='—',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'propertyStatusSelect'}),
    )
    disposal_reason = forms.ModelChoiceField(
        queryset=DisposalReason.objects.filter(status=DisposalReason.STATUS_ACTIVE).order_by('sort_order', 'name'),
        required=False,
        empty_label='— Select disposal reason —',
        label='Disposal Reason',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'disposalReasonSelect'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        property_status = cleaned_data.get('property_status')
        disposal_reason = cleaned_data.get('disposal_reason')
        if PropertyStatus.is_dispose(property_status):
            if not disposal_reason:
                self.add_error(
                    'disposal_reason',
                    'Select a disposal reason when property status is Disposed.',
                )
        else:
            cleaned_data['disposal_reason'] = None
        return cleaned_data


class EquipmentForm(forms.ModelForm):
    estimated_useful_life = forms.TypedChoiceField(
        choices=USEFUL_LIFE_CHOICES,
        coerce=_coerce_useful_life,
        empty_value='',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Useful Life (in years)',
    )

    class Meta:
        model = Equipment
        exclude = (
            'qr_code', 'created_at', 'updated_at', 'registration_batch',
            'classification', 'coa_account_code', 'expected_lifespan_years', 'fund',
            'status', 'current_location', 'condition_score', 'utilization_percent',
            'maintenance_schedule', 'last_inspection_date',
        )
        widgets = {
            'purchase_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
                'placeholder': 'dd/mm/yyyy',
            }),
            'warranty_until': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Description',
            }),
            'criterion_future_benefits': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'criterion_measurable_cost': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'criterion_useful_life': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'criterion_not_for_resale': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    # Fields managed elsewhere (detail page, signals, or view) — not on create/edit form
    _FORM_EXCLUDED_FIELDS = (
        'brand', 'model', 'asset_classification', 'depreciation_method', 'warranty_until',
        'criterion_future_benefits', 'criterion_measurable_cost',
        'criterion_useful_life', 'criterion_not_for_resale',
        'created_by',
    )

    def __init__(self, *args, **kwargs):
        self.is_create = kwargs.pop('is_create', False)
        super().__init__(*args, **kwargs)
        if 'purchase_cost' in self.fields:
            self.fields['purchase_cost'].widget = forms.HiddenInput()
        for field_name in self._FORM_EXCLUDED_FIELDS:
            self.fields.pop(field_name, None)
        if 'property_number' in self.fields:
            self.fields['property_number'].label = 'Property Number'
            self.fields['property_number'].help_text = ''
            self.fields['property_number'].widget.attrs.update({
                'class': 'form-control',
                'readonly': 'readonly',
                'placeholder': 'LGU-SANTOL-000-0000-XX-0000',
                'id': 'id_property_number',
            })
            # Validated in clean(); readonly fields are often empty on first paint.
            self.fields['property_number'].required = False
        if not self.is_create:
            self.fields.pop('assigned_user', None)
            self.fields.pop('property_status', None)
        elif 'property_status' in self.fields:
            default_property_status = PropertyStatus.default_for_new_equipment()
            self.fields['property_status'].initial = default_property_status.pk
            self.fields['property_status'].widget = forms.HiddenInput()
            self.fields['property_status'].required = False
        field_labels = {
            'name': 'Article/Item Name',
            'quantity': 'Quantity',
            'unit': 'Unit Measure',
            'acquisition_cost': 'Unit Value',
            'purchase_date': 'Date Acquired',
            'department': 'Location',
        }
        for name, label in field_labels.items():
            if name in self.fields:
                self.fields[name].label = label
        if self.is_create and 'quantity' in self.fields:
            self.fields['quantity'].widget.attrs.update({
                'min': '1',
                'max': '500',
            })
        for name, field in self.fields.items():
            if name == 'fund_source':
                field.queryset = FundSource.objects.filter(status=FundSource.STATUS_ACTIVE)
                field.label_from_instance = lambda obj: obj.display_label
                field.empty_label = 'Select Fund Source'
                field.required = False
                field.widget.attrs['class'] = 'form-select'
            elif name == 'category':
                field.queryset = Category.objects.filter(status=Category.STATUS_ACTIVE)
                field.label_from_instance = lambda obj: obj.display_label
                field.empty_label = 'Select Category'
                field.required = True
                field.widget.attrs['class'] = 'form-select'
                field.widget.attrs['id'] = 'id_category'
            elif name == 'department':
                field.queryset = Department.objects.filter(status=Department.STATUS_ACTIVE)
                field.label_from_instance = lambda obj: obj.display_label
                field.empty_label = 'Select Location'
                field.required = False
                field.widget.attrs['class'] = 'form-select'
                field.widget.attrs['id'] = 'id_department'
            elif name == 'assigned_user':
                field.queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
                field.empty_label = 'Unassigned'
                field.required = False
                field.widget.attrs['class'] = 'form-select'
            elif name == 'mode_of_procurement':
                field.queryset = ModeOfProcurement.objects.filter(status=ModeOfProcurement.STATUS_ACTIVE)
                field.empty_label = 'Select Mode of Procurement'
                field.required = False
                field.widget.attrs['class'] = 'form-select'
            elif name == 'supplier':
                field.queryset = Supplier.objects.filter(status=Supplier.STATUS_ACTIVE)
                field.empty_label = 'Select Supplier'
                field.required = False
                field.widget.attrs['class'] = 'form-select'
            elif name == 'name':
                if self.is_create:
                    category_id = None
                    if self.data.get('category'):
                        category_id = self.data.get('category')
                    elif self.initial.get('category'):
                        category_id = self.initial.get('category')
                    elif getattr(self.instance, 'category_id', None):
                        category_id = self.instance.category_id

                    item_qs = EquipmentItem.objects.none()
                    if category_id:
                        item_qs = EquipmentItem.objects.filter(
                            category_id=category_id,
                            status=EquipmentItem.STATUS_ACTIVE,
                        ).order_by('name')

                    choices = [('', 'Select Article/Item Name')] + [
                        (item.name, item.name) for item in item_qs
                    ]
                    current = ''
                    if self.data.get('name'):
                        current = normalize_equipment_name(self.data.get('name'))
                    elif self.initial.get('name'):
                        current = normalize_equipment_name(self.initial.get('name'))
                    if current and current not in dict(choices):
                        choices.append((current, current))

                    field.widget = forms.Select(attrs={
                        'class': 'form-select',
                        'id': 'id_name',
                    })
                    field.widget.choices = choices
                    field.choices = choices
                else:
                    css_class = field.widget.attrs.get('class', 'form-control')
                    field.widget.attrs['class'] = f'{css_class} text-uppercase'
            elif name == 'purchase_order_no':
                field.label = 'P.O. Number'
                field.required = False
                field.widget.attrs.update({
                    'class': 'form-control',
                    'placeholder': 'PO-2026-001',
                })
            elif name == 'payment_method':
                field.queryset = PaymentMethod.objects.filter(status=PaymentMethod.STATUS_ACTIVE)
                field.empty_label = 'Select Payment Method'
                field.required = False
                field.widget.attrs['class'] = 'form-select'
            elif name == 'estimated_useful_life':
                field.widget.attrs['class'] = 'form-select'
                if self.instance.pk and self.instance.estimated_useful_life:
                    field.initial = str(self.instance.estimated_useful_life)
                elif not self.is_create and not field.initial:
                    field.initial = '5'
            elif name in (
                'criterion_future_benefits', 'criterion_measurable_cost',
                'criterion_useful_life', 'criterion_not_for_resale',
            ):
                field.widget.attrs['class'] = 'form-check-input'
            elif 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'form-control'

        if self.is_create:
            for field_name in _CREATE_REQUIRED_FIELDS:
                field = self.fields.get(field_name)
                if not field:
                    continue
                field.required = True
                field.widget.attrs['required'] = 'required'

            if not self.is_bound and 'property_number' in self.fields:
                from django.utils import timezone
                preview = preview_property_number(
                    acquisition_cost=0,
                    purchase_date=timezone.now().date().isoformat(),
                )
                self.fields['property_number'].initial = preview['property_number']

    def clean_name(self):
        name = normalize_equipment_name(self.cleaned_data.get('name', ''))
        if not self.is_create:
            return name
        if not name:
            raise forms.ValidationError('Article/Item Name is required.')
        category = self.cleaned_data.get('category')
        # Category may not be cleaned yet when clean_name runs; fall back to raw data.
        if category is None and self.data.get('category'):
            try:
                category = Category.objects.get(pk=self.data.get('category'))
            except (Category.DoesNotExist, ValueError, TypeError):
                category = None
        if category and not EquipmentItem.objects.filter(
            category=category,
            name=name,
            status=EquipmentItem.STATUS_ACTIVE,
        ).exists():
            raise forms.ValidationError(
                'Select an Article/Item Name from the selected category.',
            )
        return name

    def clean_property_number(self):
        # On edit the primary key is only changed by the controlled rekey path.
        if self.instance and self.instance.pk and not self.is_create:
            return self.instance.property_number
        return (self.cleaned_data.get('property_number') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        if not self.is_create:
            return cleaned_data

        category = cleaned_data.get('category')
        name = cleaned_data.get('name')
        if category and name:
            if not EquipmentItem.objects.filter(
                category=category,
                name=name,
                status=EquipmentItem.STATUS_ACTIVE,
            ).exists():
                self.add_error(
                    'name',
                    'Select an Article/Item Name from the selected category.',
                )

        property_number = (cleaned_data.get('property_number') or '').strip()
        if not property_number:
            property_number = generate_property_number(
                acquisition_cost=cleaned_data.get('acquisition_cost'),
                purchase_date=cleaned_data.get('purchase_date'),
                fund_source=cleaned_data.get('fund_source'),
                category=cleaned_data.get('category'),
                department=cleaned_data.get('department'),
            )
            cleaned_data['property_number'] = property_number

        if not cleaned_data.get('property_number'):
            self.add_error(
                'property_number',
                'Property number is required. Select Fund Source, Category, and Date Acquired.',
            )
        return cleaned_data

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if self.is_create and (quantity is None or quantity < 1):
            raise forms.ValidationError('Quantity is required and must be at least 1.')
        if self.is_create and quantity is not None and quantity > 500:
            raise forms.ValidationError(
                'Quantity cannot exceed 500. Each unit is registered with its own property number.'
            )
        return quantity

    def clean_acquisition_cost(self):
        cost = self.cleaned_data.get('acquisition_cost')
        if self.is_create and (cost is None or cost <= 0):
            raise forms.ValidationError('Unit Value is required and must be greater than zero.')
        return cost

    def clean_estimated_useful_life(self):
        useful_life = self.cleaned_data.get('estimated_useful_life')
        if useful_life is None:
            return 5
        return useful_life

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.is_create:
            if not instance.brand:
                instance.brand = 'N/A'
            if not instance.property_status_id:
                instance.property_status = PropertyStatus.default_for_new_equipment()
        property_number = (self.cleaned_data.get('property_number') or '').strip()
        if property_number:
            instance.property_number = property_number
        elif self.is_create or not instance.property_number:
            instance.property_number = generate_property_number(
                acquisition_cost=instance.acquisition_cost or instance.purchase_cost,
                purchase_date=instance.purchase_date,
                fund_source=instance.fund_source,
                category=instance.category,
                department=instance.department,
                exclude_pk=instance.pk,
            )
        if commit:
            instance.save()
            self.save_m2m()
        return instance


def build_category_equipment_form(category, *args, **kwargs):
    """Equipment registration form with category fixed to the given category."""
    kwargs.setdefault('is_create', True)
    form = EquipmentForm(*args, **kwargs)
    form.fields['category'].queryset = Category.objects.filter(pk=category.pk)
    form.fields['category'].initial = category.pk
    form.fields['category'].widget = forms.HiddenInput()
    if not form.is_bound:
        from django.utils import timezone
        preview = preview_property_number(
            acquisition_cost=0,
            purchase_date=timezone.now().date().isoformat(),
            category_id=category.pk,
        )
        if 'property_number' in form.fields:
            form.fields['property_number'].initial = preview['property_number']
    return form


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'code', 'property_type_code', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Medical, Dental and Laboratory Equipment',
        })
        self.fields['code'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. 05-10',
            'maxlength': '20',
        })
        self.fields['property_type_code'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. MO',
            'maxlength': '10',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = Category.STATUS_ACTIVE


class EquipmentItemForm(forms.ModelForm):
    class Meta:
        model = EquipmentItem
        fields = ('category', 'name', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(
            status=Category.STATUS_ACTIVE,
        ).order_by('code')
        self.fields['category'].widget.attrs.update({'class': 'form-select'})
        self.fields['name'].widget.attrs.update({
            'class': 'form-control text-uppercase',
            'placeholder': 'e.g. DESKTOP COMPUTER',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = EquipmentItem.STATUS_ACTIVE

    def clean_name(self):
        return normalize_equipment_name(self.cleaned_data.get('name', ''))


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ('name', 'code', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Office of the Mayor',
        })
        self.fields['code'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. 1011',
            'maxlength': '20',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = Department.STATUS_ACTIVE


class PropertyStatusForm(forms.ModelForm):
    class Meta:
        model = PropertyStatus
        fields = ('name', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Working',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = PropertyStatus.STATUS_ACTIVE


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ('name', 'address', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. TechSource PH',
        })
        self.fields['address'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. City of San Fernando, La Union',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = Supplier.STATUS_ACTIVE


class FundSourceForm(forms.ModelForm):
    class Meta:
        model = FundSource
        fields = ('name', 'code', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Fund 101',
        })
        self.fields['code'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. 01',
            'maxlength': '20',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = FundSource.STATUS_ACTIVE


class ModeOfProcurementForm(forms.ModelForm):
    class Meta:
        model = ModeOfProcurement
        fields = ('name', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Bidding',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = ModeOfProcurement.STATUS_ACTIVE


class PaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ('name', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Cash',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = PaymentMethod.STATUS_ACTIVE


class DisposalReasonForm(forms.ModelForm):
    class Meta:
        model = DisposalReason
        fields = ('name', 'sort_order', 'status')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'e.g. Donation',
        })
        self.fields['sort_order'].widget.attrs.update({
            'class': 'form-control',
            'min': '0',
        })
        self.fields['status'].widget.attrs.update({'class': 'form-select'})
        if not self.instance.pk:
            self.fields['status'].initial = DisposalReason.STATUS_ACTIVE


class EquipmentFilterForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(
        attrs={
            'class': 'form-control',
            'placeholder': 'Search by name, property no., brand, or serial…',
            'aria-label': 'Search equipment',
        }))
    category = forms.ModelChoiceField(
        required=False,
        queryset=Category.objects.none(),
        empty_label='All Categories',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    classification = forms.ChoiceField(
        required=False,
        choices=[('', 'All Equipment Types')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Equipment Type',
    )
    property_status = forms.ModelChoiceField(
        required=False,
        queryset=PropertyStatus.objects.filter(status=PropertyStatus.STATUS_ACTIVE),
        empty_label='All Property Status',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    UNASSIGNED = 'unassigned'

    assigned_user = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    condition = forms.ChoiceField(required=False,
                                  choices=[('', 'All Conditions'),
                                           ('good', 'Good (70–100)'),
                                           ('fair', 'Fair (40–69)'),
                                           ('poor', 'Poor (0–39)')],
                                  widget=forms.Select(attrs={'class': 'form-select'}))

    @staticmethod
    def classification_choices_from_db():
        """Build Equipment Type options from distinct classification values in inventory."""
        label_map = dict(CLASSIFICATION_CHOICES)
        present = set(
            Equipment.objects.exclude(classification__isnull=True)
            .exclude(classification='')
            .values_list('classification', flat=True)
            .distinct()
        )
        choices = [('', 'All Equipment Types')]
        for key in _CLASSIFICATION_FILTER_ORDER:
            if key not in present:
                continue
            label = label_map.get(key, key)
            hint = _CLASSIFICATION_FORM_HINT.get(key)
            if hint:
                label = f'{label} ({hint})'
            choices.append((key, label))
            present.discard(key)
        for key in sorted(present):
            choices.append((key, key))
        return choices

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['classification'].choices = self.classification_choices_from_db()
        # Keep a submitted value selectable even if data changed mid-request.
        raw_classification = None
        if self.data is not None:
            raw_classification = (self.data.get('classification') or '').strip()
        elif self.initial.get('classification'):
            raw_classification = str(self.initial.get('classification')).strip()
        if raw_classification and not any(
            value == raw_classification for value, _label in self.fields['classification'].choices
        ):
            self.fields['classification'].choices = list(self.fields['classification'].choices) + [
                (raw_classification, raw_classification),
            ]

        category_ids = (
            Equipment.objects.exclude(category_id__isnull=True)
            .values_list('category_id', flat=True)
            .distinct()
        )
        self.fields['category'].queryset = (
            Category.objects.filter(pk__in=category_ids)
            .order_by('code', 'name')
        )
        self.fields['category'].label_from_instance = (
            lambda obj: obj.display_label if hasattr(obj, 'display_label') else str(obj)
        )

        status_ids = (
            Equipment.objects.exclude(property_status_id__isnull=True)
            .values_list('property_status_id', flat=True)
            .distinct()
        )
        self.fields['property_status'].queryset = (
            PropertyStatus.objects.filter(
                Q(pk__in=status_ids) | Q(status=PropertyStatus.STATUS_ACTIVE),
            )
            .distinct()
            .order_by('name')
        )

        assigned_ids = (
            Equipment.objects
            .exclude(assigned_user__isnull=True)
            .values_list('assigned_user_id', flat=True)
            .distinct()
        )
        assigned_qs = (
            User.objects.filter(is_active=True, pk__in=assigned_ids)
            .order_by('first_name', 'last_name', 'username')
        )
        if user and not user.sees_full_equipment_list():
            assigned_qs = assigned_qs.filter(pk=user.pk)
        choices = [
            ('', 'All Assigned Users'),
            (self.UNASSIGNED, 'Unassigned'),
        ]
        choices.extend(
            (str(u.pk), u.get_full_name() or u.username)
            for u in assigned_qs
        )
        self.fields['assigned_user'].choices = choices

    def clean_classification(self):
        value = (self.cleaned_data.get('classification') or '').strip()
        if not value:
            return ''
        # Exact DB match (case-sensitive stored values).
        if Equipment.objects.filter(classification=value).exists():
            return value
        # Tolerate minor case differences from older bookmarks/links.
        match = (
            Equipment.objects.exclude(classification='')
            .filter(classification__iexact=value)
            .values_list('classification', flat=True)
            .first()
        )
        if match:
            return match
        raise forms.ValidationError('Select a valid equipment type from the inventory.')

    def clean_assigned_user(self):
        value = self.cleaned_data.get('assigned_user')
        if not value:
            return None
        if value == self.UNASSIGNED:
            return self.UNASSIGNED
        try:
            return User.objects.get(pk=value, is_active=True)
        except (User.DoesNotExist, ValueError, TypeError):
            raise forms.ValidationError('Select a valid assigned user.')
