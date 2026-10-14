"""COA Forms & Ledgers views — printable PAR, ICS, SPC, SPLC, RPCSP."""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from core.decorators import insights_login_required, reports_login_required
from django.http import HttpResponse, Http404

from core.signatories import resolve_par_download_supply_officer, parse_par_export_signature

from equipment.models import Equipment, PropertyAcknowledgmentReceipt, InventoryCustodianSlip, Department, PropertyStatus
from accounts.models import User
from equipment.coa import (
    get_fund_choices,
    CLASSIFICATION_CHOICES,
    CLASSIFICATION_PPE,
    SEMI_EXPENDABLE_CLASSIFICATIONS,
    get_issuance_events,
    get_rpcsp_data,
    get_semi_expendable_equipment,
    get_ppe_equipment,
)
from equipment.par import refresh_all_par_statuses
from .coa_pdf import (
    generate_par_pdf,
    generate_all_par_pdf,
    generate_par_pdf_from_equipment,
    generate_ics_pdf,
    generate_all_ics_pdf,
    generate_spc_pdf,
    generate_all_spc_pdf,
    generate_splc_pdf,
    generate_all_splc_pdf,
    generate_rpcsp_pdf,
)


def _pdf_response(buffer, filename):
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _excel_response(buffer, filename):
    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _par_download_supply_officer(request):
    """Resolve the issuing supply officer for a PAR PDF download."""
    officer = resolve_par_download_supply_officer(
        request.user,
        request.GET.get('supply_officer'),
    )
    if officer is None:
        raise Http404(
            'Select a Supply Officer before downloading the PAR.'
        )
    return officer


def _par_pdf_kwargs(
    request, *, par=None, equipment=None, equipment_list=None,
    personnel_id=None, end_user=None,
):
    """Supply officer and end-user signatories resolved automatically from the database."""
    from core.signatories import resolve_par_received_by_user

    resolved_end_user = resolve_par_received_by_user(
        end_user=end_user,
        par=par,
        equipment=equipment,
        equipment_list=equipment_list,
        personnel_id=personnel_id,
    )
    received_by_name = (request.GET.get('received_by_name') or '').strip()
    if received_by_name:
        try:
            overrides, officer = parse_par_export_signature(request, end_user=resolved_end_user)
        except ValueError as exc:
            raise Http404(str(exc)) from exc
        kwargs = {'supply_officer': officer, 'signatory_overrides': overrides}
        if resolved_end_user:
            kwargs['end_user'] = resolved_end_user
        return kwargs
    kwargs = {'supply_officer': _par_download_supply_officer(request)}
    if resolved_end_user:
        kwargs['end_user'] = resolved_end_user
    return kwargs


def _find_issuance_event(reference_type, reference_id):
    ref_key = str(reference_id)
    for event in get_issuance_events():
        if (
            event['reference_type'] == reference_type
            and str(event['reference_id']) == ref_key
        ):
            return event
    return None


def _user_sees_all_par_register(user):
    """Admin, Property Custodian, and Supply Officer see organization-wide PAR register."""
    return user.sees_full_dashboard()


def _par_register_queryset(request):
    """Filtered PPE equipment queryset for PAR register (shared by list view and bulk download)."""
    qs = get_ppe_equipment()
    if not _user_sees_all_par_register(request.user):
        qs = qs.filter(assigned_user=request.user)

    fund = request.GET.get('fund', '')
    year = request.GET.get('year', '')
    property_status = request.GET.get('property_status', '')
    department = request.GET.get('department', '')

    if fund:
        qs = qs.filter(fund=fund)
    if year:
        try:
            qs = qs.filter(purchase_date__year=int(year))
        except ValueError:
            pass
    if property_status:
        qs = qs.filter(property_status_id=property_status)
    if department:
        qs = qs.filter(department_id=department)

    return qs, fund, year, property_status, department


def _spc_register_queryset(request):
    """Filtered semi-expendable register queryset (SPC / SPLC list and bulk download)."""
    qs = get_semi_expendable_equipment()

    fund = request.GET.get('fund', '')
    year = request.GET.get('year', '')
    status = request.GET.get('status', '')
    classification = request.GET.get('classification', '')
    department = request.GET.get('department', '')

    if fund:
        qs = qs.filter(fund=fund)
    if year:
        try:
            qs = qs.filter(purchase_date__year=int(year))
        except ValueError:
            pass
    if status:
        qs = qs.filter(status=status)
    if classification:
        qs = qs.filter(classification=classification)
    if department:
        qs = qs.filter(department_id=department)

    return qs, fund, year, status, classification, department


def _semi_expendable_register_context(qs, fund, year, status, classification, department):
    """Shared template context for SPC and SPLC register pages."""
    years = (
        get_semi_expendable_equipment()
        .exclude(purchase_date__isnull=True)
        .values_list('purchase_date__year', flat=True)
        .distinct()
    )
    year_set = sorted({y for y in years if y}, reverse=True)
    semi_classification_choices = [
        (val, label) for val, label in CLASSIFICATION_CHOICES
        if val in SEMI_EXPENDABLE_CLASSIFICATIONS
    ]
    return {
        'equipment_list': qs,
        'fund_choices': get_fund_choices(),
        'status_choices': Equipment.STATUS_CHOICES,
        'classification_choices': semi_classification_choices,
        'department_choices': Department.objects.order_by('name'),
        'selected_fund': fund,
        'selected_year': year,
        'selected_status': status,
        'selected_classification': classification,
        'selected_department': department,
        'year_choices': year_set,
        'total_count': qs.count(),
        'borrowed_count': qs.filter(status='Borrowed').count(),
        'maintenance_count': qs.filter(status='Maintenance').count(),
    }


@insights_login_required
def coa_forms_index(request):
    """COA Forms & Ledgers hub — generated documents for printing."""
    equipment_list = Equipment.objects.select_related('category', 'department').exclude(
        status='Retired'
    ).order_by('property_number')

    equipment_id = request.GET.get('equipment', '')
    selected_equipment = None
    if equipment_id:
        selected_equipment = equipment_list.filter(pk=equipment_id).first()

    semi_expendable_list = get_semi_expendable_equipment()

    issuance_events = get_issuance_events(selected_equipment)
    for event in issuance_events:
        event['par'] = PropertyAcknowledgmentReceipt.objects.filter(
            reference_type=event['reference_type'],
            reference_id=event['reference_id'],
        ).first()
        event['ics'] = InventoryCustodianSlip.objects.filter(
            reference_type=event['reference_type'],
            reference_id=event['reference_id'],
        ).first()
    rpcsp = get_rpcsp_data()

    return render(request, 'reports/coa_forms.html', {
        'equipment_list': equipment_list,
        'semi_expendable_list': semi_expendable_list,
        'selected_equipment': selected_equipment,
        'equipment_id': equipment_id,
        'issuance_events': issuance_events[:50],
        'rpcsp': rpcsp,
        'ppe_count': get_ppe_equipment().count(),
    })


@reports_login_required
def par_register(request):
    """PAR Register — PPE equipment (≥ ₱50,000) with PAR receipts."""
    from equipment.par import ensure_par_for_queryset, get_active_par_for_equipment

    refresh_all_par_statuses()
    show_all_scope = _user_sees_all_par_register(request.user)
    qs, fund, year, property_status, department = _par_register_queryset(request)
    ensure_par_for_queryset(qs, created_by=request.user)

    equipment_list = list(qs)
    due_count = 0
    par_count = 0
    for equipment in equipment_list:
        equipment.active_par = get_active_par_for_equipment(equipment)
        if equipment.active_par:
            par_count += 1
            if equipment.active_par.status == PropertyAcknowledgmentReceipt.STATUS_DUE:
                due_count += 1

    year_source = get_ppe_equipment()
    if not show_all_scope:
        year_source = year_source.filter(assigned_user=request.user)
    years = (
        year_source
        .exclude(purchase_date__isnull=True)
        .values_list('purchase_date__year', flat=True)
        .distinct()
    )
    year_set = sorted({y for y in years if y}, reverse=True)

    return render(request, 'reports/par_register.html', {
        'equipment_list': equipment_list,
        'fund_choices': get_fund_choices(),
        'property_status_choices': PropertyStatus.objects.filter(
            status=PropertyStatus.STATUS_ACTIVE,
        ).order_by('name'),
        'department_choices': Department.objects.order_by('name'),
        'selected_fund': fund,
        'selected_year': year,
        'selected_property_status': property_status,
        'selected_department': department,
        'year_choices': year_set,
        'total_count': len(equipment_list),
        'par_count': par_count,
        'due_count': due_count,
        'show_all_scope': show_all_scope,
    })


@reports_login_required
def par_print_all(request):
    """Download all filtered PAR records as one combined PAR PDF."""
    from equipment.par import ensure_par_for_queryset, get_active_par_for_equipment

    if not _user_sees_all_par_register(request.user):
        raise Http404('Access denied.')

    qs, _, _, _, _ = _par_register_queryset(request)
    ensure_par_for_queryset(qs)
    par_records = []
    for equipment in qs:
        par = get_active_par_for_equipment(equipment)
        if par:
            par_records.append(par)
    if not par_records:
        raise Http404('No PAR records match the current filters.')
    pdf_kwargs = _par_pdf_kwargs(request)
    buffer, filename = generate_all_par_pdf(par_records, **pdf_kwargs)
    return _pdf_response(buffer, filename)


@reports_login_required
def par_export_all_excel(request):
    """Download all filtered PAR records as one Excel workbook (one sheet per PAR)."""
    from equipment.par import ensure_par_for_queryset, get_active_par_for_equipment
    from .par_excel import generate_all_par_excel

    if not _user_sees_all_par_register(request.user):
        raise Http404('Access denied.')

    qs, _, _, _, _ = _par_register_queryset(request)
    ensure_par_for_queryset(qs)
    par_records = []
    for equipment in qs:
        par = get_active_par_for_equipment(equipment)
        if par:
            par_records.append(par)
    if not par_records:
        raise Http404('No PAR records match the current filters.')
    pdf_kwargs = _par_pdf_kwargs(request)
    buffer, filename = generate_all_par_excel(par_records, **pdf_kwargs)
    return _excel_response(buffer, filename)


@insights_login_required
def spc_register(request):
    """SPC Register — list semi-expendable property cards with filters."""
    qs, fund, year, status, classification, department = _spc_register_queryset(request)
    return render(request, 'reports/spc_register.html', _semi_expendable_register_context(
        qs, fund, year, status, classification, department,
    ))


@insights_login_required
def spc_print_all(request):
    """Download all filtered SPC records as one PDF."""
    qs, _, _, _, _, _ = _spc_register_queryset(request)
    if not qs.exists():
        raise Http404('No SPC records match the current filters.')
    buffer, filename = generate_all_spc_pdf(qs)
    return _pdf_response(buffer, filename)


@insights_login_required
def spc_export_all_excel(request):
    """Download all filtered SPC records as one Excel workbook."""
    from .spc_excel import generate_all_spc_excel

    qs, _, _, _, _, _ = _spc_register_queryset(request)
    if not qs.exists():
        raise Http404('No SPC records match the current filters.')
    buffer, filename = generate_all_spc_excel(qs)
    return _excel_response(buffer, filename)


@insights_login_required
def splc_register(request):
    """SPLC Register — list semi-expendable property ledger cards with filters."""
    qs, fund, year, status, classification, department = _spc_register_queryset(request)
    return render(request, 'reports/splc_register.html', _semi_expendable_register_context(
        qs, fund, year, status, classification, department,
    ))


@insights_login_required
def splc_print_all(request):
    """Download all filtered SPLC records as one PDF."""
    qs, _, _, _, _, _ = _spc_register_queryset(request)
    if not qs.exists():
        raise Http404('No SPLC records match the current filters.')
    buffer, filename = generate_all_splc_pdf(qs)
    return _pdf_response(buffer, filename)


@insights_login_required
def splc_export_all_excel(request):
    """Download all filtered SPLC records as one Excel workbook."""
    from .splc_excel import generate_all_splc_excel

    qs, _, _, _, _, _ = _spc_register_queryset(request)
    if not qs.exists():
        raise Http404('No SPLC records match the current filters.')
    buffer, filename = generate_all_splc_excel(qs)
    return _excel_response(buffer, filename)


def _ics_register_queryset(request):
    """Filtered semi-expendable equipment queryset for ICS register."""
    qs = get_semi_expendable_equipment()

    fund = request.GET.get('fund', '')
    year = request.GET.get('year', '')
    status = request.GET.get('status', '')
    classification = request.GET.get('classification', '')
    department = request.GET.get('department', '')

    if fund:
        qs = qs.filter(fund=fund)
    if year:
        try:
            qs = qs.filter(purchase_date__year=int(year))
        except ValueError:
            pass
    if status:
        qs = qs.filter(status=status)
    if classification:
        qs = qs.filter(classification=classification)
    if department:
        qs = qs.filter(department_id=department)

    return qs, fund, year, status, classification, department


@insights_login_required
def ics_register(request):
    """ICS Register — list all semi-expendable equipment with ICS slips."""
    from equipment.ics import ensure_ics_for_queryset, get_active_ics_for_equipment

    qs, fund, year, status, classification, department = _ics_register_queryset(request)
    ensure_ics_for_queryset(qs, created_by=request.user)

    equipment_list = list(
        qs.select_related(
            'department', 'assigned_user', 'supplier', 'fund_source', 'mode_of_procurement',
        )
    )
    for equipment in equipment_list:
        equipment.active_ics = get_active_ics_for_equipment(equipment)

    years = (
        get_semi_expendable_equipment()
        .exclude(purchase_date__isnull=True)
        .values_list('purchase_date__year', flat=True)
        .distinct()
    )
    year_set = sorted({y for y in years if y}, reverse=True)
    semi_classification_choices = [
        (val, label) for val, label in CLASSIFICATION_CHOICES
        if val in SEMI_EXPENDABLE_CLASSIFICATIONS
    ]

    ics_count = sum(1 for eq in equipment_list if eq.active_ics)

    return render(request, 'reports/ics_register.html', {
        'equipment_list': equipment_list,
        'fund_choices': get_fund_choices(),
        'status_choices': Equipment.STATUS_CHOICES,
        'classification_choices': semi_classification_choices,
        'department_choices': Department.objects.order_by('name'),
        'selected_fund': fund,
        'selected_year': year,
        'selected_status': status,
        'selected_classification': classification,
        'selected_department': department,
        'year_choices': year_set,
        'total_count': len(equipment_list),
        'ics_count': ics_count,
    })


@insights_login_required
def ics_print_all(request):
    """Download all filtered ICS records as one PDF."""
    from equipment.ics import ensure_ics_for_queryset, get_active_ics_for_equipment

    qs, _, _, _, _, _ = _ics_register_queryset(request)
    ensure_ics_for_queryset(qs)
    ics_records = []
    for equipment in qs:
        ics = get_active_ics_for_equipment(equipment)
        if ics:
            ics_records.append(ics)
    if not ics_records:
        raise Http404('No ICS records match the current filters.')
    buffer, filename = generate_all_ics_pdf(ics_records)
    return _pdf_response(buffer, filename)


@insights_login_required
def ics_export_all_excel(request):
    """Download all filtered ICS records as one Excel workbook (one sheet per ICS)."""
    from equipment.ics import ensure_ics_for_queryset, get_active_ics_for_equipment
    from .ics_excel import generate_all_ics_excel

    qs, _, _, _, _, _ = _ics_register_queryset(request)
    ensure_ics_for_queryset(qs)
    ics_records = []
    for equipment in qs:
        ics = get_active_ics_for_equipment(equipment)
        if ics:
            ics_records.append(ics)
    if not ics_records:
        raise Http404('No ICS records match the current filters.')
    buffer, filename = generate_all_ics_excel(ics_records)
    return _excel_response(buffer, filename)


@login_required
def ics_print_equipment(request, equipment_id):
    """Print ICS (Appendix 59) for a semi-expendable equipment item."""
    from equipment.ics import ensure_ics_for_equipment

    equipment = get_object_or_404(Equipment, pk=equipment_id)
    ics = ensure_ics_for_equipment(equipment, created_by=request.user)
    if not ics:
        raise Http404('ICS not available for this equipment.')
    buffer, filename = generate_ics_pdf(ics)
    return _pdf_response(buffer, filename)


@login_required
def ics_print(request, pk):
    """Print ICS (Appendix 59) by ICS record ID."""
    ics = get_object_or_404(
        InventoryCustodianSlip.objects.prefetch_related('items'),
        pk=pk,
    )
    buffer, filename = generate_ics_pdf(ics)
    return _pdf_response(buffer, filename)


def _resolve_assigned_user_for_par(request):
    """Resolve the end-user for an assigned-property PAR download."""
    user_id = request.GET.get('assigned_user')
    if user_id:
        try:
            target = User.objects.select_related('department', 'role').get(
                pk=int(user_id), is_active=True,
            )
        except (TypeError, ValueError, User.DoesNotExist):
            raise Http404('Invalid assigned user.')
        if not request.user.sees_full_equipment_list() and target.pk != request.user.pk:
            raise Http404('Access denied.')
        return target

    if request.user.sees_full_equipment_list():
        raise Http404('Select an assigned user before downloading the PAR.')
    return request.user


@login_required
def par_print_assigned(request):
    """Print one combined PAR (Annex A.1) for all equipment assigned to a selected user.

    Includes every active item assigned to the user on a single PAR — not just
    PPE-classified equipment — so the end-user gets one PAR covering their full
    assignment instead of having some items split off onto an ICS.
    """
    from equipment.par import ensure_par_for_queryset

    end_user = _resolve_assigned_user_for_par(request)
    qs = (
        Equipment.objects
        .select_related('category', 'department', 'assigned_user', 'supplier', 'fund_source')
        .exclude(status='Retired')
        .filter(assigned_user=end_user)
        .order_by('property_number')
    )
    if not qs.exists():
        raise Http404('No equipment is assigned to this user.')

    ensure_par_for_queryset(qs.filter(classification=CLASSIFICATION_PPE), created_by=request.user)
    pdf_kwargs = _par_pdf_kwargs(request)
    buffer, filename = generate_par_pdf_from_equipment(
        list(qs),
        end_user=end_user,
        **pdf_kwargs,
    )
    return _pdf_response(buffer, filename)


@login_required
def par_print_equipment(request, equipment_id):
    """Print PAR (Annex A.1) for a PPE equipment item."""
    from equipment.par import ensure_par_for_equipment

    equipment = get_object_or_404(
        Equipment.objects.select_related('assigned_user', 'assigned_user__role', 'assigned_user__department'),
        pk=equipment_id,
    )
    par = ensure_par_for_equipment(equipment, created_by=request.user)
    if not par:
        raise Http404('PAR not available for this equipment.')
    pdf_kwargs = _par_pdf_kwargs(request, par=par, equipment=equipment)
    buffer, filename = generate_par_pdf(par, **pdf_kwargs)
    return _pdf_response(buffer, filename)


@login_required
def par_print(request, pk):
    """Print PAR (Annex A.1) by PAR record ID."""
    par = get_object_or_404(
        PropertyAcknowledgmentReceipt.objects.prefetch_related(
            'items__equipment__assigned_user__role',
            'items__equipment__assigned_user__department',
        ),
        pk=pk,
    )
    pdf_kwargs = _par_pdf_kwargs(request, par=par)
    buffer, filename = generate_par_pdf(par, **pdf_kwargs)
    return _pdf_response(buffer, filename)


@login_required
def coa_print_par(request, reference_type, reference_id):
    """Print PAR (Annex A.1) for a PPE issuance event (by reference)."""
    par = PropertyAcknowledgmentReceipt.objects.filter(
        reference_type=reference_type,
        reference_id=str(reference_id),
    ).prefetch_related(
        'items__equipment__assigned_user__role',
        'items__equipment__assigned_user__department',
    ).first()
    if par:
        pdf_kwargs = _par_pdf_kwargs(request, par=par)
        buffer, filename = generate_par_pdf(par, **pdf_kwargs)
        return _pdf_response(buffer, filename)

    event = _find_issuance_event(reference_type, reference_id)
    if not event or event['form_type'] != 'PAR':
        raise Http404('PAR not found for this issuance.')
    from equipment.par import create_par_for_issuance
    par = create_par_for_issuance(
        event['equipment'],
        end_user=event['end_user'],
        custodian=event.get('custodian'),
        reference_type=event['reference_type'],
        reference_id=event['reference_id'],
        issue_date=event['date'],
    )
    if not par:
        raise Http404('PAR not found for this issuance.')
    pdf_kwargs = _par_pdf_kwargs(request, par=par, end_user=event['end_user'])
    buffer, filename = generate_par_pdf(par, **pdf_kwargs)
    return _pdf_response(buffer, filename)


@login_required
def coa_print_ics(request, reference_type, reference_id):
    """Print ICS (Appendix 59) for a semi-expendable issuance event."""
    ics = InventoryCustodianSlip.objects.filter(
        reference_type=reference_type,
        reference_id=str(reference_id),
    ).prefetch_related('items').first()
    if ics:
        buffer, filename = generate_ics_pdf(ics)
        return _pdf_response(buffer, filename)

    event = _find_issuance_event(reference_type, reference_id)
    if not event or event['form_type'] != 'ICS':
        raise Http404('ICS not found for this issuance.')
    from equipment.ics import create_ics_for_issuance
    ics = create_ics_for_issuance(
        event['equipment'],
        end_user=event['end_user'],
        custodian=event.get('custodian'),
        reference_type=event['reference_type'],
        reference_id=event['reference_id'],
        issue_date=event['date'],
    )
    if not ics:
        raise Http404('ICS not found for this issuance.')
    buffer, filename = generate_ics_pdf(ics)
    return _pdf_response(buffer, filename)


@login_required
def coa_print_spc(request, equipment_id):
    """Print Semi-Expendable Property Card (Annex A.2) for equipment."""
    equipment = get_object_or_404(Equipment, pk=equipment_id)
    buffer, filename = generate_spc_pdf(equipment)
    return _pdf_response(buffer, filename)


@login_required
def coa_export_spc_excel(request, equipment_id):
    """Export Semi-Expendable Property Card (Annex A.2) as Excel."""
    from .spc_excel import generate_spc_excel

    equipment = get_object_or_404(Equipment, pk=equipment_id)
    buffer, filename = generate_spc_excel(equipment)
    return _excel_response(buffer, filename)


@insights_login_required
def coa_print_all_spc(request):
    """Print all Semi-Expendable Property Cards in one PDF."""
    equipment_qs = get_semi_expendable_equipment()
    if not equipment_qs.exists():
        raise Http404('No semi-expendable equipment found.')
    buffer, filename = generate_all_spc_pdf(equipment_qs)
    return _pdf_response(buffer, filename)


@insights_login_required
def coa_print_all_splc(request):
    """Print all Semi-Expendable Property Ledger Cards (Annex A.3) in one PDF."""
    equipment_qs = get_semi_expendable_equipment()
    if not equipment_qs.exists():
        raise Http404('No semi-expendable equipment found.')
    buffer, filename = generate_all_splc_pdf(equipment_qs)
    return _pdf_response(buffer, filename)


@login_required
def coa_print_splc(request, equipment_id):
    """Print Semi-Expendable Property Ledger Card (Annex A.3) for equipment."""
    equipment = get_object_or_404(Equipment, pk=equipment_id)
    buffer, filename = generate_splc_pdf(equipment)
    return _pdf_response(buffer, filename)


@login_required
def coa_export_splc_excel(request, equipment_id):
    """Export Semi-Expendable Property Ledger Card (Annex A.3) as Excel."""
    from .splc_excel import generate_splc_excel

    equipment = get_object_or_404(Equipment, pk=equipment_id)
    buffer, filename = generate_splc_excel(equipment)
    return _excel_response(buffer, filename)


@insights_login_required
def coa_print_rpcsp(request):
    """Print RPCSP reconciliation report (Annex A.4)."""
    buffer, filename = generate_rpcsp_pdf()
    return _pdf_response(buffer, filename)
