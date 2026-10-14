from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import ngettext
from .models import (
    Equipment, Department, Category, EquipmentItem, PropertyStatus, FundSource, ModeOfProcurement, PaymentMethod, DisposalReason, Supplier,
    EquipmentAssignmentHistory,
    ChartOfAccount, AccountingEntry,
    PropertyAcknowledgmentReceipt, PropertyAcknowledgmentReceiptItem,
    InventoryCustodianSlip, InventoryCustodianSlipItem,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'status')
    list_filter = ('status',)
    search_fields = ('name', 'code')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'property_type_code', 'name', 'status')
    list_filter = ('status',)
    search_fields = ('name', 'code', 'property_type_code')


@admin.register(EquipmentItem)
class EquipmentItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'status')
    list_filter = ('status', 'category')
    search_fields = ('name', 'category__name', 'category__code')


@admin.register(PropertyStatus)
class PropertyStatusAdmin(admin.ModelAdmin):
    list_display = ('name', 'status')
    list_filter = ('status',)
    search_fields = ('name',)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'status')
    list_filter = ('status',)
    search_fields = ('name', 'address')


@admin.register(FundSource)
class FundSourceAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'status')
    list_filter = ('status',)
    search_fields = ('name', 'code')


@admin.register(ModeOfProcurement)
class ModeOfProcurementAdmin(admin.ModelAdmin):
    list_display = ('name', 'status')
    list_filter = ('status',)
    search_fields = ('name',)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'status')
    list_filter = ('status',)
    search_fields = ('name',)


@admin.register(DisposalReason)
class DisposalReasonAdmin(admin.ModelAdmin):
    list_display = ('sort_order', 'name', 'status')
    list_filter = ('status',)
    search_fields = ('name',)
    ordering = ('sort_order', 'name')


@admin.register(ChartOfAccount)
class ChartOfAccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'account_type')
    list_filter = ('account_type',)
    filter_horizontal = ('categories',)


@admin.register(AccountingEntry)
class AccountingEntryAdmin(admin.ModelAdmin):
    list_display = ('jev_number', 'equipment', 'entry_type', 'amount', 'fund', 'created_at')
    list_filter = ('entry_type', 'fund')
    search_fields = ('jev_number', 'equipment__name', 'equipment__property_number')
    readonly_fields = ('jev_number', 'created_at')


class EquipmentAssignmentHistoryInline(admin.TabularInline):
    model = EquipmentAssignmentHistory
    extra = 0
    fields = ('user_name', 'previous_user_name', 'changed_by', 'notes', 'assigned_at')
    readonly_fields = ('user_name', 'previous_user_name', 'changed_by', 'notes', 'assigned_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # View-only inline: avoids formset FK mismatch when property_number (PK) is edited.
        return False


class EquipmentAdminForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = '__all__'

    def clean_property_number(self):
        value = (self.cleaned_data.get('property_number') or '').strip()
        if not value:
            raise forms.ValidationError('Property number is required.')
        from .property_number import property_number_is_taken
        exclude_pk = self.instance.pk if self.instance.pk else None
        if property_number_is_taken(value, exclude_pk=exclude_pk):
            raise forms.ValidationError('This property number is already in use.')
        return value


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    form = EquipmentAdminForm
    list_display = (
        'property_number', 'name', 'category', 'fund_source',
        'mode_of_procurement', 'property_status', 'supplier', 'assigned_user', 'status', 'condition_score',
    )
    list_filter = ('status', 'fund_source', 'mode_of_procurement', 'property_status', 'supplier', 'category')
    search_fields = ('property_number', 'name', 'serial_number', 'brand')
    readonly_fields = (
        'classification', 'coa_account_code',
        'current_book_value', 'qr_code',
    )
    autocomplete_fields = ('assigned_user',)
    fieldsets = (
        ('Identification', {
            'fields': ('property_number', 'name', 'category', 'asset_classification',
                       'brand', 'model', 'serial_number'),
        }),
        ('Acquisition', {
            'fields': ('purchase_date', 'purchase_cost', 'acquisition_cost', 'fund', 'fund_source',
                       'mode_of_procurement', 'purchase_order_no', 'quantity', 'unit',
                       'estimated_useful_life', 'depreciation_method',
                       'warranty_until', 'supplier'),
        }),
        ('COA Classification', {
            'fields': ('classification', 'coa_account_code',
                       'criterion_future_benefits', 'criterion_measurable_cost',
                       'criterion_useful_life', 'criterion_not_for_resale'),
        }),
        ('Location & Assignment', {
            'fields': ('department', 'current_location', 'assigned_user'),
        }),
        ('Status & Condition', {
            'fields': ('status', 'property_status', 'disposal_reason', 'expected_lifespan_years', 'condition_score', 'utilization_percent',
                       'maintenance_schedule', 'last_inspection_date'),
        }),
        ('Other', {
            'fields': ('current_book_value', 'qr_code'),
        }),
    )
    inlines = (EquipmentAssignmentHistoryInline,)

    def save_model(self, request, obj, form, change):
        obj._assignment_changed_by = request.user
        if not change:
            from .property_number import save_new_equipment_with_property_number
            if not obj.property_number:
                save_new_equipment_with_property_number(obj)
                return
            super().save_model(request, obj, form, change)
            return

        old_pk = form.initial.get('property_number')
        new_pk = form.cleaned_data.get('property_number')
        if new_pk != old_pk:
            from .property_number import rekey_equipment_to_property_number
            try:
                rekeyed = rekey_equipment_to_property_number(obj, new_pk, old_pk=old_pk)
            except IntegrityError as exc:
                raise ValidationError({
                    'property_number': 'This property number is already in use.',
                }) from exc
            request._admin_equipment_new_pk = rekeyed.pk
            return

        super().save_model(request, obj, form, change)
        from .property_number import rekey_equipment_for_edit
        rekeyed = rekey_equipment_for_edit(obj)
        if rekeyed.pk != old_pk:
            request._admin_equipment_new_pk = rekeyed.pk

    def response_change(self, request, obj):
        new_pk = getattr(request, '_admin_equipment_new_pk', None)
        if new_pk and new_pk != obj.pk:
            if '_continue' in request.POST:
                return HttpResponseRedirect(
                    reverse('admin:equipment_equipment_change', args=[new_pk]),
                )
            if '_addanother' in request.POST:
                return HttpResponseRedirect(reverse('admin:equipment_equipment_add'))
            return HttpResponseRedirect(reverse('admin:equipment_equipment_changelist'))
        return super().response_change(request, obj)

    def get_deleted_objects(self, objs, request):
        """Allow delete confirmation when only PAR/ICS line items block CASCADE."""
        from django.contrib.admin.utils import NestedObjects
        from django.db import router

        to_delete, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request,
        )
        if not protected:
            return to_delete, model_count, perms_needed, protected

        try:
            obj = objs[0]
        except IndexError:
            return to_delete, model_count, perms_needed, protected

        using = router.db_for_write(obj._meta.model)
        collector = NestedObjects(using=using, origin=objs)
        collector.collect(objs)
        removable = {
            related for related in collector.protected
            if isinstance(related, (PropertyAcknowledgmentReceiptItem, InventoryCustodianSlipItem))
        }
        if removable and removable == set(collector.protected):
            return to_delete, model_count, perms_needed, []
        return to_delete, model_count, perms_needed, protected

    def delete_model(self, request, obj):
        label = str(obj)
        obj.hard_delete(deleted_by=request.user)
        self.message_user(
            request,
            f'Equipment "{label}" was permanently deleted.',
            messages.SUCCESS,
        )

    def delete_queryset(self, request, queryset):
        count = queryset.count()
        for obj in queryset:
            obj.hard_delete(deleted_by=request.user)
        self.message_user(
            request,
            ngettext(
                '%d equipment record was permanently deleted.',
                '%d equipment records were permanently deleted.',
                count,
            ) % count,
            messages.SUCCESS,
        )


@admin.register(EquipmentAssignmentHistory)
class EquipmentAssignmentHistoryAdmin(admin.ModelAdmin):
    list_display = ('equipment', 'user_name', 'previous_user_name', 'notes', 'changed_by', 'assigned_at')
    list_filter = ('notes',)
    search_fields = ('equipment__name', 'equipment__property_number', 'user_name', 'previous_user_name')
    readonly_fields = ('equipment', 'user', 'user_name', 'previous_user_name', 'changed_by', 'notes', 'assigned_at')


class PropertyAcknowledgmentReceiptItemInline(admin.TabularInline):
    model = PropertyAcknowledgmentReceiptItem
    extra = 0
    readonly_fields = (
        'equipment', 'quantity', 'unit', 'description',
        'property_number', 'date_acquired', 'amount',
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PropertyAcknowledgmentReceipt)
class PropertyAcknowledgmentReceiptAdmin(admin.ModelAdmin):
    list_display = ('par_no', 'fund', 'end_user', 'custodian', 'date_issued', 'renewal_due_date', 'status')
    list_filter = ('status', 'fund')
    search_fields = ('par_no', 'end_user__username', 'items__property_number')
    readonly_fields = ('par_no', 'lgu', 'renewal_due_date', 'created_at')
    inlines = (PropertyAcknowledgmentReceiptItemInline,)


class InventoryCustodianSlipItemInline(admin.TabularInline):
    model = InventoryCustodianSlipItem
    extra = 0
    readonly_fields = (
        'equipment', 'quantity', 'unit', 'description', 'amount',
        'inventory_item_no', 'estimated_unit_cost', 'total_cost', 'useful_life',
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(InventoryCustodianSlip)
class InventoryCustodianSlipAdmin(admin.ModelAdmin):
    list_display = (
        'ics_no', 'entity_name', 'supplier_name', 'fund', 'date', 'received_by',
        'received_from', 'status',
    )
    list_filter = ('status', 'fund')
    search_fields = ('ics_no', 'entity_name', 'supplier_name', 'items__inventory_item_no')
    readonly_fields = ('ics_no', 'lgu', 'created_at')
    fieldsets = (
        (None, {
            'fields': (
                'ics_no', 'lgu', 'entity_name', 'fund_cluster', 'fund', 'date', 'status',
            ),
        }),
        ('Supplier (per slip)', {
            'fields': ('supplier_name',),
            'description': 'Supplier name printed on this ICS. Address, P.O. #, Date, and MOP use Site Settings defaults.',
        }),
        ('Reference', {
            'fields': (
                'received_by', 'received_from',
                'received_by_position', 'received_from_position',
                'date_received_by', 'date_received_from',
                'reference_type', 'reference_id', 'superseded_by', 'created_at',
            ),
        }),
    )
    inlines = (InventoryCustodianSlipItemInline,)
