"""Views for borrowing app."""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Avg, Count, F, ExpressionWrapper, fields
from .models import BorrowRequest
from .forms import BorrowRequestForm, ApprovalForm
from equipment.models import Equipment
from core.models import AuditLog, Notification


@login_required
def borrow_list(request):
    """List borrow requests with analytics."""
    # Auto-flag overdue
    active = BorrowRequest.objects.filter(approval_status='Approved', actual_return__isnull=True)
    for req in active:
        req.check_and_flag_overdue()

    qs = BorrowRequest.objects.select_related('employee', 'equipment', 'department', 'approver')

    # Filter for non-admin: show only own requests
    if not (request.user.is_admin or request.user.is_custodian):
        qs = qs.filter(employee=request.user)

    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(approval_status=status_filter)

    paginator = Paginator(qs.order_by('-created_at'), 15)
    page = paginator.get_page(request.GET.get('page'))

    # Analytics
    total = BorrowRequest.objects.count()
    overdue_count = BorrowRequest.objects.filter(approval_status='Overdue').count()
    returned = BorrowRequest.objects.filter(actual_return__isnull=False)

    from django.db.models import F, FloatField
    avg_return_days = 0
    if returned.exists():
        durations = [(r.actual_return - r.borrow_date).days for r in returned]
        avg_return_days = sum(durations) / len(durations)

    borrow_rate = round((total / max(Equipment.objects.count(), 1)) * 100, 1)

    top_borrowed = (
        Equipment.objects.annotate(borrow_count=Count('borrow_requests'))
        .order_by('-borrow_count')[:5]
    )

    return render(request, 'borrowing/list.html', {
        'page_obj': page,
        'status_filter': status_filter,
        'status_choices': BorrowRequest.STATUS_CHOICES,
        'total': total,
        'overdue_count': overdue_count,
        'avg_return_days': round(avg_return_days, 1),
        'borrow_rate': borrow_rate,
        'top_borrowed': top_borrowed,
    })


@login_required
def borrow_create(request):
    """Create a new borrow request."""
    form = BorrowRequestForm()
    if request.method == 'POST':
        form = BorrowRequestForm(request.POST)
        if form.is_valid():
            br = form.save(commit=False)
            br.employee = request.user
            br.department = request.user.department
            br.save()
            # Notify custodians
            from accounts.models import User
            for custodian in User.objects.filter(
                role__can_manage_borrowing=True,
                role__status='Active',
                is_active=True,
            ):
                Notification.objects.create(
                    user=custodian,
                    message=f'New borrow request from {request.user.get_full_name() or request.user.username} for {br.equipment.name}.',
                    type='borrow',
                )
            AuditLog.objects.create(
                user=request.user, action='CREATE',
                model_name='BorrowRequest', object_id=br.pk,
                details=f'Borrow request for {br.equipment.name}'
            )
            messages.success(request, 'Borrow request submitted successfully.')
            return redirect('borrowing:list')
    return render(request, 'borrowing/form.html', {'form': form, 'title': 'New Borrow Request'})


@login_required
def borrow_detail(request, pk):
    """View borrow request details and approve/reject."""
    br = get_object_or_404(BorrowRequest, pk=pk)
    form = None

    if request.user.is_admin or request.user.is_custodian:
        form = ApprovalForm()
        if request.method == 'POST':
            form = ApprovalForm(request.POST)
            if form.is_valid():
                action = form.cleaned_data['action']
                notes = form.cleaned_data['notes']
                br.approval_status = action
                br.approver = request.user
                br.approver_notes = notes
                br.save()

                # Update equipment status
                if action == 'Approved':
                    br.equipment.status = 'Borrowed'
                    br.equipment.save()
                    # COA: generate PAR or ICS + expense entry on issuance
                    from equipment.coa import process_issuance
                    result = process_issuance(
                        br.equipment,
                        end_user=br.employee,
                        custodian=request.user,
                        reference_type='BorrowRequest',
                        reference_id=br.pk,
                        created_by=request.user,
                    )
                    form_label = result['form_type']
                    par = result.get('par')
                    if par:
                        messages.info(
                            request,
                            f'PAR {par.par_no} issued for {br.equipment.name}. '
                            f'Download from equipment detail or PAR Register.',
                        )
                    else:
                        messages.info(
                            request,
                            f'{form_label} issuance recorded for {br.equipment.name}. '
                            f'Print from COA Forms & Ledgers.',
                        )
                elif action == 'Rejected':
                    pass  # Equipment remains Available

                Notification.objects.create(
                    user=br.employee,
                    message=f'Your borrow request for {br.equipment.name} has been {action.lower()}.',
                    type='borrow',
                )
                AuditLog.objects.create(
                    user=request.user, action=action.upper(),
                    model_name='BorrowRequest', object_id=br.pk,
                    details=f'Borrow request {action} for {br.equipment.name}'
                )
                messages.success(request, f'Request {action} successfully.')
                return redirect('borrowing:list')

    return render(request, 'borrowing/detail.html', {'br': br, 'form': form})


@login_required
def borrow_return(request, pk):
    """Mark equipment as returned."""
    br = get_object_or_404(BorrowRequest, pk=pk)
    if request.method == 'POST':
        br.actual_return = timezone.now().date()
        br.approval_status = 'Returned'
        br.save()
        br.equipment.status = 'Available'
        br.equipment.save()
        AuditLog.objects.create(
            user=request.user, action='RETURN',
            model_name='BorrowRequest', object_id=br.pk,
            details=f'Returned: {br.equipment.name}'
        )
        messages.success(request, f'{br.equipment.name} marked as returned.')
    return redirect('borrowing:list')
