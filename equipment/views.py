"""Views for equipment app."""
import re
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, ProtectedError, Count, OuterRef, Subquery, IntegerField, DateTimeField, F, Sum
from django.db.models.functions import Coalesce
from urllib.parse import urlencode
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.clickjacking import xframe_options_sameorigin
from .models import Equipment, Department, Category, EquipmentItem, PropertyStatus, FundSource, ModeOfProcurement, PaymentMethod, DisposalReason, Supplier, EquipmentRepair
from .property_number import (
    preview_property_number,
    save_new_equipment_with_property_number,
    rekey_equipment_for_edit,
    unique_property_numbers_enabled,
)
from .forms import (
    EquipmentForm, EquipmentFilterForm, CategoryForm, EquipmentItemForm, DepartmentForm,
    AssignUserForm, UpdatePropertyStatusForm, EquipmentRepairForm, PropertyStatusForm, FundSourceForm, ModeOfProcurementForm,
    PaymentMethodForm, DisposalReasonForm, SupplierForm, build_category_equipment_form,
)
from .coa import preview_coa_classification, apply_coa_standards_to_all
from .inventory_tag import build_qr_data_uri, get_inventory_tag_context
from .qr_export import parse_qr_export_options, build_qr_items, build_qr_codes_zip
from core.models import AuditLog


def _can_manage_settings(user):
    return user.is_admin or user.is_custodian


def _can_manage_equipment(user):
    return user.is_admin or user.is_custodian


def _sync_equipment_qr(equipment):
    """Ensure the stored QR image reflects the latest equipment details."""
    if equipment.property_number and equipment.ensure_qr_code_current():
        equipment.refresh_from_db(fields=['qr_code'])


def _can_print_inventory_tag(user):
    return user.is_admin or user.is_custodian or user.is_supply_officer


# Alias kept for any cached imports / older references
_can_register_equipment = _can_manage_equipment


def _filter_equipment_for_user(qs, user):
    """Global search and cross-app queries respect full inventory access."""
    if user.can_view_all_equipment():
        return qs
    return qs.filter(assigned_user=user)


def _filter_equipment_list_for_user(qs, user):
    """Equipment inventory page: admin, custodian, supply officer, and technician see all rows."""
    if user.sees_full_equipment_list():
        return qs
    return qs.filter(assigned_user=user)


def _filter_equipment_for_dashboard(qs, user):
    """Dashboard: full inventory for admin/custodian/supply officer; own items for others."""
    if user.sees_full_dashboard():
        return qs
    return qs.filter(assigned_user=user)


def _user_can_access_equipment(user, equipment):
    if user.can_view_all_equipment():
        return True
    return equipment.assigned_user_id == user.pk


def _apply_equipment_filter_form(qs, form):
    """Apply EquipmentFilterForm filters to an equipment queryset."""
    if not form.is_valid():
        return qs

    search = form.cleaned_data.get('search')
    category = form.cleaned_data.get('category')
    classification = form.cleaned_data.get('classification')
    property_status = form.cleaned_data.get('property_status')
    assigned_user = form.cleaned_data.get('assigned_user')
    condition = form.cleaned_data.get('condition')

    if search:
        qs = qs.filter(
            Q(property_number__icontains=search) |
            Q(name__icontains=search) |
            Q(brand__icontains=search) |
            Q(serial_number__icontains=search)
        )
    if category:
        qs = qs.filter(category=category)
    if classification:
        qs = qs.filter(classification=classification)
    if property_status:
        qs = qs.filter(property_status=property_status)
    if assigned_user == EquipmentFilterForm.UNASSIGNED:
        qs = qs.filter(assigned_user__isnull=True)
    elif assigned_user:
        qs = qs.filter(assigned_user=assigned_user)
    if condition == 'good':
        qs = qs.filter(condition_score__gte=70)
    elif condition == 'fair':
        qs = qs.filter(condition_score__gte=40, condition_score__lt=70)
    elif condition == 'poor':
        qs = qs.filter(condition_score__lt=40)
    return qs


def _annotate_registration_batches(qs):
    """Attach batch size and batch registered-at for inventory grouping."""
    from django.db.models import Max

    batch_size_sq = (
        Equipment.objects.filter(registration_batch=OuterRef('registration_batch'))
        .exclude(registration_batch__isnull=True)
        .order_by()
        .values('registration_batch')
        .annotate(c=Count('property_number'))
        .values('c')[:1]
    )
    batch_time_sq = (
        Equipment.objects.filter(registration_batch=OuterRef('registration_batch'))
        .exclude(registration_batch__isnull=True)
        .order_by()
        .values('registration_batch')
        .annotate(m=Max('created_at'))
        .values('m')[:1]
    )
    return qs.annotate(
        batch_size=Coalesce(
            Subquery(batch_size_sq, output_field=IntegerField()),
            1,
        ),
        batch_registered_at=Coalesce(
            Subquery(batch_time_sq, output_field=DateTimeField()),
            F('created_at'),
        ),
    )


@login_required
def equipment_list(request):
    """Filterable, searchable, paginated equipment inventory."""
    qs = Equipment.objects.select_related(
        'assigned_user', 'category', 'property_status', 'fund_source',
        'mode_of_procurement', 'supplier', 'created_by', 'department',
    )
    qs = _filter_equipment_list_for_user(qs, request.user)
    form = EquipmentFilterForm(request.GET, user=request.user)
    selected_assigned_user = None
    selected_assigned_par_count = 0
    selected_batch = None
    selected_batch_count = 0

    batch_raw = (request.GET.get('batch') or '').strip()
    if batch_raw:
        try:
            selected_batch = uuid.UUID(batch_raw)
            qs = qs.filter(registration_batch=selected_batch)
        except (ValueError, TypeError, AttributeError):
            selected_batch = None

    if form.is_valid():
        assigned_user = form.cleaned_data.get('assigned_user')
        if assigned_user and assigned_user != EquipmentFilterForm.UNASSIGNED:
            selected_assigned_user = assigned_user
            selected_assigned_par_count = Equipment.objects.exclude(
                status='Retired',
            ).filter(assigned_user=assigned_user).count()
        qs = _apply_equipment_filter_form(qs, form)

    qs = _annotate_registration_batches(qs)
    if selected_batch:
        selected_batch_count = qs.count()
        qs = qs.order_by('property_number')
    else:
        # Keep registration siblings together, newest groups first.
        qs = qs.order_by('-batch_registered_at', 'registration_batch', 'property_number')

    paginator = Paginator(qs, 15 if not selected_batch else 50)
    page = paginator.get_page(request.GET.get('page'))
    assigned_par_count = Equipment.objects.exclude(
        status='Retired',
    ).filter(assigned_user=request.user).count()

    clear_batch_params = request.GET.copy()
    clear_batch_params.pop('batch', None)
    clear_batch_params.pop('page', None)

    return render(request, 'equipment/list.html', {
        'page_obj': page,
        'filter_form': form,
        'total_count': qs.count(),
        'employee_own_view': not request.user.sees_full_equipment_list(),
        'assigned_par_count': assigned_par_count,
        'can_print_assigned_par': request.user.sees_full_equipment_list(),
        'selected_assigned_user': selected_assigned_user,
        'selected_assigned_par_count': selected_assigned_par_count,
        'can_print_qr_codes': _can_print_inventory_tag(request.user),
        'selected_batch': selected_batch,
        'selected_batch_count': selected_batch_count,
        'clear_batch_query': clear_batch_params.urlencode(),
    })


def _equipment_list_filter_params(request):
    """Copy GET params for equipment list exports, stripping pagination and export options."""
    filter_params = request.GET.copy()
    filter_params.pop('page', None)
    for key in ('qr_size', 'qr_resolution', 'qr_spacing', 'show_name', 'action'):
        filter_params.pop(key, None)
    return filter_params


def _get_filtered_equipment_queryset(request, *, exclude_retired=False):
    """Return filtered equipment queryset and filter form for list exports."""
    qs = Equipment.objects.select_related(
        'assigned_user', 'category', 'property_status', 'fund_source', 'department',
    ).order_by('property_number')
    if exclude_retired:
        qs = qs.exclude(status='Retired', property_number='')
    qs = _filter_equipment_list_for_user(qs, request.user)

    filter_params = _equipment_list_filter_params(request)
    form = EquipmentFilterForm(filter_params, user=request.user)
    qs = _apply_equipment_filter_form(qs, form)
    return qs, form, filter_params


def _get_qr_export_queryset(request):
    """Return filtered equipment queryset and filter form for QR export."""
    return _get_filtered_equipment_queryset(request, exclude_retired=True)


def _qr_export_filter_summary(form):
    parts = []
    if not form.is_valid():
        return parts
    if form.cleaned_data.get('category'):
        parts.append(f"Category: {form.cleaned_data['category'].name}")
    if form.cleaned_data.get('classification'):
        parts.append(f"Type: {form.cleaned_data['classification']}")
    if form.cleaned_data.get('search'):
        parts.append(f"Search: {form.cleaned_data['search']}")
    assigned_user = form.cleaned_data.get('assigned_user')
    if assigned_user == EquipmentFilterForm.UNASSIGNED:
        parts.append('Assigned User: Unassigned')
    elif assigned_user:
        parts.append(f"Assigned User: {assigned_user.get_full_name() or assigned_user.username}")
    return parts


@login_required
@xframe_options_sameorigin
def equipment_qr_codes_print_all(request):
    """Printable sheet of QR codes for filtered equipment."""
    if not _can_print_inventory_tag(request.user):
        messages.error(request, 'Only Admin, Property Custodian, or Supply Officer can print QR codes.')
        return redirect('equipment:list')

    options = parse_qr_export_options(request.GET)
    qs, form, filter_params = _get_qr_export_queryset(request)
    qr_items = build_qr_items(qs, options, for_print=True)

    return render(request, 'equipment/qr_codes_print_all.html', {
        'qr_items': qr_items,
        'total_count': len(qr_items),
        'filter_summary': _qr_export_filter_summary(form),
        'options': options,
        'back_url': (
            f"{reverse('equipment:list')}?{urlencode(filter_params, doseq=True)}"
            if filter_params else reverse('equipment:list')
        ),
    })


@login_required
def equipment_list_export_excel(request):
    """Download filtered equipment as PAR (Appendix 71) Excel."""
    from django.http import Http404
    from equipment.coa import CLASSIFICATION_PPE
    from equipment.par import ensure_par_for_queryset
    from core.signatories import resolve_par_received_by_user
    from reports.coa_views import _par_pdf_kwargs
    from reports.par_excel import generate_par_excel

    qs, form, filter_params = _get_filtered_equipment_queryset(request)
    qs = qs.exclude(status='Retired').select_related(
        'assigned_user', 'assigned_user__role', 'assigned_user__department',
        'category', 'department', 'supplier', 'fund_source',
    )
    equipment_list = list(qs)
    if not equipment_list:
        messages.warning(request, 'No equipment matched your filters.')
        if filter_params:
            return redirect(f"{reverse('equipment:list')}?{urlencode(filter_params, doseq=True)}")
        return redirect('equipment:list')

    assigned_user = form.cleaned_data.get('assigned_user') if form.is_valid() else None
    if assigned_user == EquipmentFilterForm.UNASSIGNED:
        assigned_user = None
    end_user = resolve_par_received_by_user(
        end_user=assigned_user,
        equipment_list=equipment_list,
    )

    try:
        pdf_kwargs = _par_pdf_kwargs(
            request,
            equipment_list=equipment_list,
            end_user=end_user,
        )
    except Http404 as exc:
        messages.error(request, str(exc))
        if filter_params:
            return redirect(f"{reverse('equipment:list')}?{urlencode(filter_params, doseq=True)}")
        return redirect('equipment:list')

    ensure_par_for_queryset(
        qs.filter(classification=CLASSIFICATION_PPE),
        created_by=request.user,
    )

    output, filename = generate_par_excel(
        equipment_list,
        end_user=pdf_kwargs.get('end_user', end_user),
        supply_officer=pdf_kwargs.get('supply_officer'),
        signatory_overrides=pdf_kwargs.get('signatory_overrides'),
    )
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def equipment_qr_codes_download(request):
    """Download filtered equipment QR codes as a ZIP of PNG files."""
    if not _can_print_inventory_tag(request.user):
        messages.error(request, 'Only Admin, Property Custodian, or Supply Officer can download QR codes.')
        return redirect('equipment:list')

    options = parse_qr_export_options(request.GET)
    qs, form, _filter_params = _get_qr_export_queryset(request)
    qr_items = build_qr_items(qs, options, for_print=False)
    if not qr_items:
        messages.warning(request, 'No equipment matched your filters.')
        return redirect('equipment:list')

    zip_buffer = build_qr_codes_zip(qr_items, options)
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="equipment_qr_codes.zip"'
    return response


@login_required
@xframe_options_sameorigin
def equipment_inventory_tag_print(request, pk):
    """Printable COA Circular 80-124 inventory tag for a single equipment item."""
    equipment = get_object_or_404(
        Equipment.objects.select_related(
            'department', 'assigned_user', 'property_status', 'category',
            'supplier', 'mode_of_procurement', 'fund_source',
        ),
        pk=pk,
    )
    if not _user_can_access_equipment(request.user, equipment):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')
    if not _can_print_inventory_tag(request.user):
        messages.error(request, 'Only Admin, Property Custodian, or Supply Officer can print inventory tags.')
        return redirect('equipment:list')
    if not equipment.allows_inventory_tag:
        messages.error(
            request,
            'Inventory tags cannot be printed for disposed or unserviceable equipment.',
        )
        return redirect('equipment:detail', pk=pk)
    _sync_equipment_qr(equipment)
    context = get_inventory_tag_context(equipment, request=request)

    if 'date_counted' in request.GET:
        raw_date_counted = request.GET.get('date_counted', '').strip()
        context['date_counted'] = parse_date(raw_date_counted) if raw_date_counted else None
    if 'representative_name' in request.GET:
        context['representative_name'] = request.GET.get('representative_name', '').strip()

    return render(request, 'equipment/inventory_tag_print.html', context)


@login_required
def equipment_lookup(request):
    """Lookup equipment by scanned QR code (full label, property number, or equipment ID)."""
    code = request.GET.get('code', '').strip()
    if not code:
        return JsonResponse({'found': False, 'error': 'No code provided.'}, status=400)

    equipment = Equipment.find_by_scanned_code(code)

    if not equipment:
        return JsonResponse({
            'found': False,
            'error': f'No equipment found for "{code[:80]}".',
        })

    if not _user_can_access_equipment(request.user, equipment):
        return JsonResponse({
            'found': False,
            'error': 'You do not have access to this equipment record.',
        })

    return JsonResponse({
        'found': True,
        'id': equipment.pk,
        'property_number': equipment.property_number,
        'name': equipment.display_name,
        'status': equipment.status,
        'url': reverse('equipment:detail', args=[equipment.pk]),
    })


def _registration_batch_summary(equipment):
    """Summary of units registered together with this equipment (multi-quantity create)."""
    from django.db.models import Max, Sum

    batch_id = getattr(equipment, 'registration_batch', None)
    if not batch_id:
        return None

    siblings = Equipment.objects.filter(registration_batch=batch_id).order_by('property_number')
    count = siblings.count()
    if count <= 1:
        return None

    first = siblings.first()
    last = siblings.last()
    totals = siblings.aggregate(
        total_cost=Sum('acquisition_cost'),
        registered_at=Max('created_at'),
    )
    return {
        'batch_id': batch_id,
        'count': count,
        'first_property_number': first.property_number,
        'last_property_number': last.property_number,
        'unit_cost': equipment.acquisition_cost,
        'total_cost': totals['total_cost'] or 0,
        'registered_at': totals['registered_at'],
    }


@login_required
def equipment_detail(request, pk):
    """View detailed information about a single equipment item."""
    equipment = get_object_or_404(
        Equipment.objects.select_related(
            'department', 'assigned_user', 'category', 'property_status', 'disposal_reason',
            'fund_source', 'mode_of_procurement', 'supplier', 'payment_method',
        ),
        pk=pk,
    )
    if not _user_can_access_equipment(request.user, equipment):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')
    from equipment.par import get_active_par_for_equipment
    from equipment.ics import get_active_ics_for_equipment, ensure_ics_for_equipment
    assignment_history = equipment.assignment_history.select_related('changed_by', 'user')
    repairs = equipment.repairs.select_related('recorded_by')
    repair_form = EquipmentRepairForm() if _can_manage_equipment(request.user) else None
    active_par = get_active_par_for_equipment(equipment) if equipment.classification == 'PPE' else None
    active_ics = None
    if equipment.classification != 'PPE':
        active_ics = get_active_ics_for_equipment(equipment)
        if not active_ics:
            active_ics = ensure_ics_for_equipment(equipment, created_by=request.user)
    assign_form = None
    property_status_form = None
    dispose_status = PropertyStatus.objects.filter(
        name__iexact=PropertyStatus.DISPOSE_STATUS,
        status=PropertyStatus.STATUS_ACTIVE,
    ).first()
    if request.user.is_admin or request.user.is_custodian:
        assign_form = AssignUserForm(initial={'assigned_user': equipment.assigned_user})
        property_status_form = UpdatePropertyStatusForm(initial={
            'property_status': equipment.property_status,
            'disposal_reason': equipment.disposal_reason,
        })
    _sync_equipment_qr(equipment)
    qr_payload = equipment.get_qr_payload() if equipment.property_number else ''
    registration_batch = _registration_batch_summary(equipment)
    return render(request, 'equipment/detail.html', {
        'equipment': equipment,
        'assignment_history': assignment_history,
        'repairs': repairs,
        'repair_form': repair_form,
        'active_par': active_par,
        'active_ics': active_ics,
        'assign_form': assign_form,
        'property_status_form': property_status_form,
        'dispose_status_id': dispose_status.pk if dispose_status else '',
        'show_disposal_reason': PropertyStatus.is_dispose(equipment.property_status) or bool(equipment.disposal_reason_id),
        'qr_code_data': build_qr_data_uri(qr_payload, box_size=8, border=3) if qr_payload else '',
        'registration_batch': registration_batch,
    })


@login_required
def equipment_assign_user(request, pk):
    """Update the assigned user for equipment (admin/custodian only)."""
    if not (request.user.is_admin or request.user.is_custodian):
        messages.error(request, 'Access denied.')
        return redirect('equipment:detail', pk=pk)

    equipment = get_object_or_404(Equipment, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:detail', pk=pk)

    form = AssignUserForm(request.POST)
    if form.is_valid():
        new_user = form.cleaned_data['assigned_user']
        if equipment.assigned_user != new_user:
            equipment.assigned_user = new_user
            equipment._assignment_changed_by = request.user
            equipment.save(update_fields=['assigned_user', 'updated_at'])
            label = new_user or 'Unassigned'
            messages.success(request, f'Assigned user updated to {label}.')
        else:
            messages.info(request, 'No change to assigned user.')
    else:
        messages.error(request, 'Invalid assigned user selection.')
    return redirect('equipment:detail', pk=pk)


@login_required
def equipment_repair_add(request, pk):
    """Record a repair that posts to the PPE ledger card."""
    if not _can_manage_equipment(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:detail', pk=pk)

    equipment = get_object_or_404(Equipment, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:detail', pk=pk)

    form = EquipmentRepairForm(request.POST)
    if form.is_valid():
        repair = form.save(commit=False)
        repair.equipment = equipment
        repair.recorded_by = request.user
        repair.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='EquipmentRepair', object_id=str(repair.pk),
            details=(
                f'{repair.nature} repair of {repair.amount} on {repair.repair_date} '
                f'for {equipment.property_number}'
            ),
        )
        messages.success(request, 'Repair recorded. It will appear on the PPE ledger card.')
    else:
        errors = '; '.join(
            err for field_errors in form.errors.values() for err in field_errors
        )
        messages.error(request, errors or 'Could not save the repair.')
    return redirect('equipment:detail', pk=pk)


@login_required
def equipment_repair_delete(request, pk, repair_pk):
    """Remove a repair from the equipment and the PPE ledger card."""
    if not _can_manage_equipment(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:detail', pk=pk)
    if request.method != 'POST':
        return redirect('equipment:detail', pk=pk)

    repair = get_object_or_404(EquipmentRepair, pk=repair_pk, equipment_id=pk)
    label = f'{repair.nature} repair on {repair.repair_date}'
    repair.delete()
    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='EquipmentRepair', object_id=str(repair_pk),
        details=f'Removed {label} from {pk}',
    )
    messages.success(request, 'Repair removed.')
    return redirect('equipment:detail', pk=pk)


@login_required
def equipment_update_property_status(request, pk):
    """Update property status for equipment (admin/custodian only)."""
    if not (request.user.is_admin or request.user.is_custodian):
        messages.error(request, 'Access denied.')
        return redirect('equipment:detail', pk=pk)

    equipment = get_object_or_404(Equipment, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:detail', pk=pk)

    form = UpdatePropertyStatusForm(request.POST)
    if form.is_valid():
        new_status = form.cleaned_data['property_status']
        new_disposal_reason = form.cleaned_data['disposal_reason']
        status_changed = equipment.property_status != new_status
        reason_changed = equipment.disposal_reason != new_disposal_reason
        if status_changed or reason_changed:
            equipment.property_status = new_status
            equipment.disposal_reason = new_disposal_reason
            equipment._assignment_changed_by = request.user
            equipment.save(update_fields=['property_status', 'disposal_reason', 'updated_at'])
            if PropertyStatus.is_dispose(new_status) and new_disposal_reason:
                label = f'{new_status} ({new_disposal_reason})'
            else:
                label = new_status or '—'
            messages.success(request, f'Property status updated to {label}.')
        else:
            messages.info(request, 'No change to property status.')
    else:
        messages.error(request, 'Invalid property status selection.')
    return redirect('equipment:detail', pk=pk)


@login_required
def location_list(request):
    """List office / department locations with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    qs = Department.objects.all().order_by('code')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    total_count = qs.count()
    active_count = qs.filter(status=Department.STATUS_ACTIVE).count()

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'equipment/location_list.html', {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': DepartmentForm(),
        'total_count': total_count,
        'active_count': active_count,
        'inactive_count': total_count - active_count,
        'equipment_total': Equipment.objects.filter(department__in=qs).count(),
    })


@login_required
def department_create(request):
    """Create a new office / department location."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:location_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:location_list')

    form = DepartmentForm(request.POST)
    if form.is_valid():
        department = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='Department', object_id=department.pk,
            details=f'Added location: {department.name} ({department.code})',
        )
        if is_ajax:
            return JsonResponse({
                'success': True,
                'id': department.pk,
                'name': department.display_label,
            })
        messages.success(request, f'Location "{department.name}" added.')
    else:
        errors = '; '.join(
            err for field_errors in form.errors.values() for err in field_errors
        )
        if is_ajax:
            return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
        messages.error(request, errors or 'Could not add location.')
    return redirect('equipment:location_list')


@login_required
def location_edit(request, pk):
    """Update an office / department location."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:location_list')

    obj = get_object_or_404(Department, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:location_list')

    form = DepartmentForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        for equipment in Equipment.objects.filter(department=obj):
            equipment.current_location = obj.name
            equipment.save(update_fields=['current_location', 'updated_at'])
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='Department', object_id=obj.pk,
            details=f'Updated location: {obj.name} ({obj.code})',
        )
        messages.success(request, f'Location "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update location.')
    return redirect('equipment:location_list')


@login_required
def location_delete(request, pk):
    """Delete an office / department location."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:location_list')

    obj = get_object_or_404(Department, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:location_list')

    label = f'{obj.name} ({obj.code})'
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{obj.name}" because it is assigned to equipment.',
        )
        return redirect('equipment:location_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='Department', object_id=pk,
        details=f'Deleted location: {label}',
    )
    messages.success(request, f'Location "{obj.name}" deleted.')
    return redirect('equipment:location_list')


def _open_category_id(request):
    """Category panel to reopen after an article/item change."""
    raw = (request.GET.get('open') or '').strip()
    return raw if raw.isdigit() else ''


def _redirect_category_list(request, category_pk=None):
    """Return to the category list, keeping search and the open panel."""
    params = {}
    for key in ('search', 'per_page', 'page'):
        value = (request.POST.get(key) or '').strip()
        if value:
            params[key] = value
    if category_pk and str(category_pk).isdigit():
        params['open'] = str(category_pk)
    url = reverse('equipment:category_list')
    if params:
        return redirect(f'{url}?{urlencode(params)}')
    return redirect(url)


def _category_list_context(request, equipment_form=None, open_equipment_category=None):
    """Shared context for the category list and category equipment modal."""
    from django.db.models import Prefetch

    qs = Category.objects.annotate(
        equipment_count=Count('equipment', distinct=True),
        item_count=Count('items', distinct=True),
    ).order_by('code')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(code__icontains=search)
            | Q(property_type_code__icontains=search)
        )

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    totals = qs.aggregate(
        equipment_total=Sum('equipment_count'),
        item_total=Sum('item_count'),
    )
    total_count = qs.count()
    active_count = qs.filter(status=Category.STATUS_ACTIVE).count()

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    # Load registered equipment for categories on this page only.
    page_category_ids = [c.pk for c in page.object_list]
    if page_category_ids:
        categories_with_equipment = (
            Category.objects.filter(pk__in=page_category_ids)
            .prefetch_related(
                Prefetch(
                    'equipment',
                    queryset=Equipment.objects.select_related(
                        'department',
                        'property_status',
                        'assigned_user',
                    ).order_by('property_number'),
                ),
                Prefetch(
                    'items',
                    queryset=EquipmentItem.objects.order_by('name'),
                ),
            )
        )
        equipment_by_category = {c.pk: c for c in categories_with_equipment}
        for category in page.object_list:
            loaded = equipment_by_category.get(category.pk)
            category.prefetched_equipment = (
                list(loaded.equipment.all()) if loaded else []
            )
            category.prefetched_items = (
                list(loaded.items.all()) if loaded else []
            )
    else:
        for category in page.object_list:
            category.prefetched_equipment = []
            category.prefetched_items = []

    return {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': CategoryForm(),
        'total_count': total_count,
        'active_count': active_count,
        'inactive_count': total_count - active_count,
        'item_total': totals['item_total'] or 0,
        'equipment_total': totals['equipment_total'] or 0,
        'departments': Department.objects.filter(status=Department.STATUS_ACTIVE).order_by('name'),
        'fund_sources': FundSource.objects.filter(status=FundSource.STATUS_ACTIVE).order_by('name'),
        'equipment_form': equipment_form,
        'open_equipment_category': open_equipment_category,
        'open_category_id': _open_category_id(request),
    }


@login_required
def category_list(request):
    """List equipment categories with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    return render(request, 'equipment/category_list.html', _category_list_context(request))


@login_required
def category_create(request):
    """Create a new equipment category (AJAX or settings form)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:category_list')

    form = CategoryForm(request.POST)
    if form.is_valid():
        category = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='Category', object_id=category.pk,
            details=f'Added category: {category.name} ({category.code})',
        )
        if is_ajax:
            return JsonResponse({
                'success': True,
                'id': category.pk,
                'name': category.display_label,
            })
        messages.success(request, f'Category "{category.name}" added.')
    else:
        errors = '; '.join(
            err for field_errors in form.errors.values() for err in field_errors
        )
        if is_ajax:
            return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
        messages.error(request, errors or 'Could not add category.')
    return redirect('equipment:category_list')


@login_required
def category_edit(request, pk):
    """Update an equipment category."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    obj = get_object_or_404(Category, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:category_list')

    form = CategoryForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='Category', object_id=obj.pk,
            details=f'Updated category: {obj.name} ({obj.code})',
        )
        messages.success(request, f'Category "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update category.')
    return redirect('equipment:category_list')


@login_required
def category_delete(request, pk):
    """Delete an equipment category."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    obj = get_object_or_404(Category, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:category_list')

    label = f'{obj.name} ({obj.code})'
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{obj.name}" because it is assigned to equipment.',
        )
        return redirect('equipment:category_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='Category', object_id=pk,
        details=f'Deleted category: {label}',
    )
    messages.success(request, f'Category "{obj.name}" deleted.')
    return redirect('equipment:category_list')


@login_required
def equipment_item_list(request):
    """Return active article/item names for a category (AJAX)."""
    if not _can_manage_equipment(request.user):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    category_id = request.GET.get('category') or request.GET.get('category_id')
    if not category_id:
        return JsonResponse({'success': True, 'items': []})

    try:
        category = Category.objects.get(pk=int(category_id))
    except (Category.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid category.'}, status=400)

    items = list(
        EquipmentItem.objects.filter(
            category=category,
            status=EquipmentItem.STATUS_ACTIVE,
        ).order_by('name').values('id', 'name')
    )
    return JsonResponse({'success': True, 'items': items, 'category_id': category.pk})


@login_required
def equipment_item_create(request):
    """Create an article/item name under a category (AJAX or form)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:category_list')

    form = EquipmentItemForm(request.POST)
    if form.is_valid():
        item = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='EquipmentItem', object_id=item.pk,
            details=f'Added item: {item.name} under {item.category.code}',
        )
        if is_ajax:
            return JsonResponse({
                'success': True,
                'id': item.pk,
                'name': item.name,
                'category_id': item.category_id,
            })
        messages.success(request, f'Item "{item.name}" added under {item.category.name}.')
        return _redirect_category_list(request, item.category_id)

    errors = '; '.join(
        err for field_errors in form.errors.values() for err in field_errors
    )
    if is_ajax:
        return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
    messages.error(request, errors or 'Could not add item.')
    category_id = request.POST.get('category')
    return _redirect_category_list(request, category_id if str(category_id).isdigit() else None)


@login_required
def equipment_item_edit(request, pk):
    """Update an article/item catalog name."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    obj = get_object_or_404(EquipmentItem, pk=pk)
    if request.method != 'POST':
        return _redirect_category_list(request, obj.category_id)

    form = EquipmentItemForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='EquipmentItem', object_id=obj.pk,
            details=f'Updated item: {obj.name} under {obj.category.code}',
        )
        messages.success(request, f'Item "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update item.')
    return _redirect_category_list(request, obj.category_id)


@login_required
def equipment_item_delete(request, pk):
    """Delete an article/item catalog name."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    obj = get_object_or_404(EquipmentItem, pk=pk)
    if request.method != 'POST':
        return _redirect_category_list(request, obj.category_id)

    label = obj.name
    category_id = obj.category_id
    category_code = obj.category.code
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{label}" because it is still in use.',
        )
        return _redirect_category_list(request, category_id)

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='EquipmentItem', object_id=pk,
        details=f'Deleted item: {label} under {category_code}',
    )
    messages.success(request, f'Item "{label}" deleted.')
    return _redirect_category_list(request, category_id)


@login_required
def category_equipment_create(request, pk):
    """Register equipment under a specific category (from category list modal)."""
    if not _can_manage_equipment(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:category_list')

    category = get_object_or_404(Category, pk=pk)
    if category.status != Category.STATUS_ACTIVE:
        messages.error(request, 'Cannot add equipment to an inactive category.')
        return redirect('equipment:category_list')

    if request.method != 'POST':
        return redirect('equipment:category_list')

    post_data = request.POST.copy()
    post_data['category'] = str(category.pk)
    form = build_category_equipment_form(category, post_data)
    if form.is_valid():
        equipment = form.save(commit=False)
        equipment.category = category
        equipment.created_by = request.user
        equipment._assignment_changed_by = request.user
        equipment.registration_batch = uuid.uuid4()
        save_new_equipment_with_property_number(equipment)
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='Equipment', object_id=equipment.pk,
            details=(
                f'Registered under {category.code}: '
                f'{equipment.name} ({equipment.property_number})'
            ),
        )
        messages.success(
            request,
            f'Equipment "{equipment.name}" registered under {category.name}.',
        )
        return redirect('equipment:detail', pk=equipment.pk)

    errors = '; '.join(
        err for field_errors in form.errors.values() for err in field_errors
    )
    messages.error(request, errors or 'Could not register equipment. Check the form and try again.')
    context = _category_list_context(
        request,
        equipment_form=form,
        open_equipment_category=category,
    )
    return render(request, 'equipment/category_list.html', context)


@login_required
def property_number_generate(request):
    """Return an auto-generated property number (AJAX)."""
    if not _can_manage_equipment(request.user):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    exclude_pk = request.GET.get('exclude_pk')
    if exclude_pk:
        exclude_pk = str(exclude_pk).strip() or None
    else:
        exclude_pk = None

    try:
        count = int(request.GET.get('count') or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, 500))

    try:
        preview = preview_property_number(
            acquisition_cost=request.GET.get('acquisition_cost', '0'),
            purchase_date=request.GET.get('purchase_date') or None,
            fund_source_id=request.GET.get('fund_source') or None,
            category_id=request.GET.get('category') or None,
            department_id=request.GET.get('department') or None,
            exclude_pk=exclude_pk,
            current_property_number=request.GET.get('current_property_number') or None,
            count=count,
        )
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid input.'}, status=400)

    return JsonResponse({'success': True, **preview})


def _copy_equipment_unit(source):
    """Build a new unsaved Equipment with the same registration details as ``source``."""
    skip = {
        'property_number', 'qr_code', 'created_at', 'updated_at',
    }
    clone = Equipment()
    for field in Equipment._meta.concrete_fields:
        if field.primary_key or field.name in skip:
            continue
        setattr(clone, field.attname, getattr(source, field.attname))
    clone.quantity = 1
    return clone


@login_required
def coa_classify_preview(request):
    """Live COA Circular 3.1 classification preview (AJAX)."""
    if not (request.user.is_admin or request.user.is_custodian):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    def _bool_param(name, default=True):
        raw = request.GET.get(name)
        if raw is None:
            return default
        return raw.lower() in ('1', 'true', 'on', 'yes')

    try:
        preview = preview_coa_classification(
            acquisition_cost=request.GET.get('acquisition_cost', '0'),
            category_id=request.GET.get('category') or None,
            criterion_future_benefits=_bool_param('criterion_future_benefits'),
            criterion_measurable_cost=_bool_param('criterion_measurable_cost'),
            criterion_useful_life=_bool_param('criterion_useful_life'),
            criterion_not_for_resale=_bool_param('criterion_not_for_resale'),
        )
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid input.'}, status=400)

    return JsonResponse({'success': True, **preview})


@login_required
def coa_apply_standards(request):
    """Recompute COA classification for all equipment (admin/custodian only)."""
    if not (request.user.is_admin or request.user.is_custodian):
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)

    updated = apply_coa_standards_to_all()
    return JsonResponse({'success': True, 'updated': updated})


@login_required
def equipment_create(request):
    """Register new equipment."""
    if not _can_manage_equipment(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    initial = {}
    category_id = request.GET.get('category')
    if category_id:
        try:
            selected_category = Category.objects.get(
                pk=int(category_id),
                status=Category.STATUS_ACTIVE,
            )
            initial['category'] = selected_category.pk
        except (Category.DoesNotExist, ValueError, TypeError):
            pass

    form = EquipmentForm(is_create=True, initial=initial)
    if request.method == 'POST':
        form = EquipmentForm(request.POST, is_create=True)
        if form.is_valid():
            quantity = form.cleaned_data.get('quantity') or 1
            equipment = form.save(commit=False)
            equipment.created_by = request.user
            equipment._assignment_changed_by = request.user
            if not unique_property_numbers_enabled():
                equipment.quantity = quantity
                save_new_equipment_with_property_number(equipment)
                AuditLog.objects.create(
                    user=request.user, action='CREATE',
                    model_name='Equipment', object_id=equipment.pk,
                    details=(
                        f'Registered: {equipment.name} ({equipment.property_number})'
                        + (f' — {quantity} units, shared property number' if quantity > 1 else '')
                    ),
                )
                if quantity == 1:
                    messages.success(
                        request,
                        f'Equipment {equipment.name} registered successfully.',
                    )
                else:
                    messages.success(
                        request,
                        (
                            f'Registered {quantity} units of {equipment.name} '
                            f'under one property number: {equipment.property_number}.'
                        ),
                    )
                return redirect('equipment:detail', pk=equipment.pk)

            # Each physical unit is registered separately with its own property number.
            equipment.quantity = 1
            equipment.registration_batch = uuid.uuid4()

            created = []
            for index in range(quantity):
                unit = equipment if index == 0 else _copy_equipment_unit(equipment)
                if index > 0:
                    unit.created_by = request.user
                    unit._assignment_changed_by = request.user
                save_new_equipment_with_property_number(unit)
                AuditLog.objects.create(
                    user=request.user, action='CREATE',
                    model_name='Equipment', object_id=unit.pk,
                    details=(
                        f'Registered: {unit.name} ({unit.property_number})'
                        + (f' [unit {index + 1} of {quantity}]' if quantity > 1 else '')
                    ),
                )
                created.append(unit)

            if quantity == 1:
                messages.success(
                    request,
                    f'Equipment {created[0].name} registered successfully.',
                )
                return redirect('equipment:detail', pk=created[0].pk)

            first = created[0].property_number
            last = created[-1].property_number
            if quantity <= 10:
                detail = ', '.join(eq.property_number for eq in created)
            else:
                detail = f'{first} … {last}'
            messages.success(
                request,
                (
                    f'Registered {quantity} individual units of {created[0].name} '
                    f'with separate property numbers: {detail}.'
                ),
            )
            batch_url = reverse('equipment:list') + f'?batch={created[0].registration_batch}'
            return redirect(batch_url)
    return render(request, 'equipment/form.html', {
        'form': form,
        'title': 'Register Equipment',
        'is_create': True,
        'equipment': None,
    })


@login_required
def equipment_edit(request, pk):
    """Edit equipment details."""
    equipment = get_object_or_404(Equipment, pk=pk)
    if not _can_manage_equipment(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')
    form = EquipmentForm(instance=equipment)
    if request.method == 'POST':
        form = EquipmentForm(request.POST, instance=equipment)
        if form.is_valid():
            equipment = form.save(commit=False)
            equipment._assignment_changed_by = request.user
            equipment.save()
            equipment = rekey_equipment_for_edit(equipment)
            AuditLog.objects.create(
                user=request.user, action='UPDATE',
                model_name='Equipment', object_id=equipment.pk,
                details=f'Updated: {equipment.name}'
            )
            messages.success(request, f'Equipment {equipment.name} updated.')
            return redirect('equipment:detail', pk=equipment.pk)
    return render(request, 'equipment/form.html', {
        'form': form,
        'title': 'Edit Equipment',
        'equipment': equipment,
        'is_create': False,
    })


@login_required
def equipment_archive(request, pk):
    """Archive (retire) equipment."""
    equipment = get_object_or_404(Equipment, pk=pk)
    if not _can_manage_equipment(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')
    if request.method == 'POST':
        equipment.status = 'Retired'
        equipment.save()
        AuditLog.objects.create(
            user=request.user, action='ARCHIVE',
            model_name='Equipment', object_id=equipment.pk,
            details=f'Archived: {equipment.name}'
        )
        messages.success(request, f'Equipment {equipment.name} archived.')
    return redirect('equipment:list')


@login_required
def property_status_list(request):
    """List property statuses with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    qs = PropertyStatus.objects.all().order_by('name')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(name__icontains=search)

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    total_count = qs.count()
    active_count = qs.filter(status=PropertyStatus.STATUS_ACTIVE).count()
    disposal_reasons = DisposalReason.objects.all().order_by('sort_order', 'name')
    reason_total = disposal_reasons.count()

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'equipment/property_status_list.html', {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': PropertyStatusForm(),
        'total_count': total_count,
        'active_count': active_count,
        'inactive_count': total_count - active_count,
        'equipment_total': Equipment.objects.filter(property_status__in=qs).count(),
        'reason_total': reason_total,
        'reason_active': disposal_reasons.filter(status=DisposalReason.STATUS_ACTIVE).count(),
        'disposal_reasons': disposal_reasons,
        'disposal_reason_form': DisposalReasonForm(),
    })


@login_required
def property_status_create(request):
    """Create a property status."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:property_status_list')

    if request.method != 'POST':
        return redirect('equipment:property_status_list')

    form = PropertyStatusForm(request.POST)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='PropertyStatus', object_id=obj.pk,
            details=f'Added property status: {obj.name}',
        )
        messages.success(request, f'Property status "{obj.name}" added.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not add property status.')
    return redirect('equipment:property_status_list')


@login_required
def property_status_edit(request, pk):
    """Update a property status."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:property_status_list')

    obj = get_object_or_404(PropertyStatus, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:property_status_list')

    form = PropertyStatusForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='PropertyStatus', object_id=obj.pk,
            details=f'Updated property status: {obj.name}',
        )
        messages.success(request, f'Property status "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update property status.')
    return redirect('equipment:property_status_list')


@login_required
def property_status_delete(request, pk):
    """Delete a property status."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:property_status_list')

    obj = get_object_or_404(PropertyStatus, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:property_status_list')

    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{name}" because it is assigned to equipment.',
        )
        return redirect('equipment:property_status_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='PropertyStatus', object_id=pk,
        details=f'Deleted property status: {name}',
    )
    messages.success(request, f'Property status "{name}" deleted.')
    return redirect('equipment:property_status_list')


@login_required
def disposal_reason_create(request):
    """Create a disposal reason."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:property_status_list')

    if request.method != 'POST':
        return redirect('equipment:property_status_list')

    form = DisposalReasonForm(request.POST)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='DisposalReason', object_id=obj.pk,
            details=f'Added disposal reason: {obj.name}',
        )
        messages.success(request, f'Disposal reason "{obj.name}" added.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not add disposal reason.')
    return redirect('equipment:property_status_list')


@login_required
def disposal_reason_edit(request, pk):
    """Update a disposal reason."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:property_status_list')

    obj = get_object_or_404(DisposalReason, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:property_status_list')

    form = DisposalReasonForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='DisposalReason', object_id=obj.pk,
            details=f'Updated disposal reason: {obj.name}',
        )
        messages.success(request, f'Disposal reason "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update disposal reason.')
    return redirect('equipment:property_status_list')


@login_required
def disposal_reason_delete(request, pk):
    """Delete a disposal reason."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:property_status_list')

    obj = get_object_or_404(DisposalReason, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:property_status_list')

    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{name}" because it is assigned to equipment.',
        )
        return redirect('equipment:property_status_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='DisposalReason', object_id=pk,
        details=f'Deleted disposal reason: {name}',
    )
    messages.success(request, f'Disposal reason "{name}" deleted.')
    return redirect('equipment:property_status_list')


@login_required
def supplier_list(request):
    """List suppliers with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    qs = Supplier.objects.all().order_by('name')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(name__icontains=search)

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'equipment/supplier_list.html', {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': SupplierForm(),
        'total_count': qs.count(),
    })


@login_required
def supplier_create(request):
    """Create a supplier."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:supplier_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:supplier_list')

    form = SupplierForm(request.POST)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='Supplier', object_id=obj.pk,
            details=f'Added supplier: {obj.name}',
        )
        if is_ajax:
            return JsonResponse({'success': True, 'id': obj.pk, 'name': obj.name})
        messages.success(request, f'Supplier "{obj.name}" added.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        if is_ajax:
            return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
        messages.error(request, errors or 'Could not add supplier.')
    return redirect('equipment:supplier_list')


@login_required
def supplier_edit(request, pk):
    """Update a supplier."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:supplier_list')

    obj = get_object_or_404(Supplier, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:supplier_list')

    form = SupplierForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='Supplier', object_id=obj.pk,
            details=f'Updated supplier: {obj.name}',
        )
        messages.success(request, f'Supplier "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update supplier.')
    return redirect('equipment:supplier_list')


@login_required
def supplier_delete(request, pk):
    """Delete a supplier."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:supplier_list')

    obj = get_object_or_404(Supplier, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:supplier_list')

    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{name}" because it is assigned to equipment.',
        )
        return redirect('equipment:supplier_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='Supplier', object_id=pk,
        details=f'Deleted supplier: {name}',
    )
    messages.success(request, f'Supplier "{name}" deleted.')
    return redirect('equipment:supplier_list')


@login_required
def fund_source_list(request):
    """List fund sources with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    qs = FundSource.objects.all().order_by('code')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    total_count = qs.count()
    active_count = qs.filter(status=FundSource.STATUS_ACTIVE).count()
    equipment_totals = Equipment.objects.filter(fund_source__in=qs).aggregate(
        equipment_total=Count('pk'),
        acquisition_total=Sum('acquisition_cost'),
    )

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'equipment/fund_source_list.html', {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': FundSourceForm(),
        'total_count': total_count,
        'active_count': active_count,
        'inactive_count': total_count - active_count,
        'equipment_total': equipment_totals['equipment_total'] or 0,
        'acquisition_total': equipment_totals['acquisition_total'] or 0,
    })


@login_required
def fund_source_create(request):
    """Create a fund source."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:fund_source_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:fund_source_list')

    form = FundSourceForm(request.POST)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='FundSource', object_id=obj.pk,
            details=f'Added fund source: {obj.name} ({obj.code})',
        )
        if is_ajax:
            return JsonResponse({'success': True, 'id': obj.pk, 'name': obj.display_label})
        messages.success(request, f'Fund source "{obj.name}" added.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        if is_ajax:
            return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
        messages.error(request, errors or 'Could not add fund source.')
    return redirect('equipment:fund_source_list')


@login_required
def fund_source_edit(request, pk):
    """Update a fund source."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:fund_source_list')

    obj = get_object_or_404(FundSource, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:fund_source_list')

    form = FundSourceForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        for equipment in Equipment.objects.filter(fund_source=obj):
            equipment.fund = obj.name
            equipment.save(update_fields=['fund', 'updated_at'])
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='FundSource', object_id=obj.pk,
            details=f'Updated fund source: {obj.name} ({obj.code})',
        )
        messages.success(request, f'Fund source "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update fund source.')
    return redirect('equipment:fund_source_list')


@login_required
def fund_source_delete(request, pk):
    """Delete a fund source."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:fund_source_list')

    obj = get_object_or_404(FundSource, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:fund_source_list')

    label = f'{obj.name} ({obj.code})'
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{obj.name}" because it is assigned to equipment.',
        )
        return redirect('equipment:fund_source_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='FundSource', object_id=pk,
        details=f'Deleted fund source: {label}',
    )
    messages.success(request, f'Fund source "{obj.name}" deleted.')
    return redirect('equipment:fund_source_list')


@login_required
def procurement_mode_list(request):
    """List modes of procurement with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    qs = ModeOfProcurement.objects.all().order_by('name')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(name__icontains=search)

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'equipment/procurement_mode_list.html', {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': ModeOfProcurementForm(),
        'total_count': qs.count(),
    })


@login_required
def procurement_mode_create(request):
    """Create a mode of procurement."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:procurement_mode_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:procurement_mode_list')

    form = ModeOfProcurementForm(request.POST)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='ModeOfProcurement', object_id=obj.pk,
            details=f'Added mode of procurement: {obj.name}',
        )
        if is_ajax:
            return JsonResponse({'success': True, 'id': obj.pk, 'name': obj.name})
        messages.success(request, f'Mode of procurement "{obj.name}" added.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        if is_ajax:
            return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
        messages.error(request, errors or 'Could not add mode of procurement.')
    return redirect('equipment:procurement_mode_list')


@login_required
def payment_method_list(request):
    """List payment methods with search and pagination."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:list')

    qs = PaymentMethod.objects.all().order_by('name')
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(name__icontains=search)

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    per_page = per_page if per_page in (10, 20, 50) else 10

    paginator = Paginator(qs, per_page)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'equipment/payment_method_list.html', {
        'page_obj': page,
        'search': search,
        'per_page': per_page,
        'form': PaymentMethodForm(),
        'total_count': qs.count(),
    })


@login_required
def payment_method_create(request):
    """Create a payment method."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _can_manage_settings(request.user):
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('equipment:payment_method_list')

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)
        return redirect('equipment:payment_method_list')

    form = PaymentMethodForm(request.POST)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='CREATE',
            model_name='PaymentMethod', object_id=obj.pk,
            details=f'Added payment method: {obj.name}',
        )
        if is_ajax:
            return JsonResponse({'success': True, 'id': obj.pk, 'name': obj.name})
        messages.success(request, f'Payment method "{obj.name}" added.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        if is_ajax:
            return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)
        messages.error(request, errors or 'Could not add payment method.')
    return redirect('equipment:payment_method_list')


@login_required
def payment_method_edit(request, pk):
    """Update a payment method."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:payment_method_list')

    obj = get_object_or_404(PaymentMethod, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:payment_method_list')

    form = PaymentMethodForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='PaymentMethod', object_id=obj.pk,
            details=f'Updated payment method: {obj.name}',
        )
        messages.success(request, f'Payment method "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update payment method.')
    return redirect('equipment:payment_method_list')


@login_required
def payment_method_delete(request, pk):
    """Delete a payment method."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:payment_method_list')

    obj = get_object_or_404(PaymentMethod, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:payment_method_list')

    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{name}" because it is assigned to equipment.',
        )
        return redirect('equipment:payment_method_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='PaymentMethod', object_id=pk,
        details=f'Deleted payment method: {name}',
    )
    messages.success(request, f'Payment method "{name}" deleted.')
    return redirect('equipment:payment_method_list')


@login_required
def procurement_mode_edit(request, pk):
    """Update a mode of procurement."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:procurement_mode_list')

    obj = get_object_or_404(ModeOfProcurement, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:procurement_mode_list')

    form = ModeOfProcurementForm(request.POST, instance=obj)
    if form.is_valid():
        obj = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='ModeOfProcurement', object_id=obj.pk,
            details=f'Updated mode of procurement: {obj.name}',
        )
        messages.success(request, f'Mode of procurement "{obj.name}" updated.')
    else:
        errors = '; '.join(err for errs in form.errors.values() for err in errs)
        messages.error(request, errors or 'Could not update mode of procurement.')
    return redirect('equipment:procurement_mode_list')


@login_required
def procurement_mode_delete(request, pk):
    """Delete a mode of procurement."""
    if not _can_manage_settings(request.user):
        messages.error(request, 'Access denied.')
        return redirect('equipment:procurement_mode_list')

    obj = get_object_or_404(ModeOfProcurement, pk=pk)
    if request.method != 'POST':
        return redirect('equipment:procurement_mode_list')

    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete "{name}" because it is assigned to equipment.',
        )
        return redirect('equipment:procurement_mode_list')

    AuditLog.objects.create(
        user=request.user, action='DELETE',
        model_name='ModeOfProcurement', object_id=pk,
        details=f'Deleted mode of procurement: {name}',
    )
    messages.success(request, f'Mode of procurement "{name}" deleted.')
    return redirect('equipment:procurement_mode_list')
