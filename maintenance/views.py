"""Views for maintenance app."""
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Avg
from django.utils import timezone
from .models import MaintenanceRequest
from .forms import MaintenanceRequestForm, MaintenanceUpdateForm
from equipment.models import Equipment
from core.models import AuditLog, Notification
import json


@login_required
def maintenance_list(request):
    """List maintenance requests with analytics."""
    qs = MaintenanceRequest.objects.select_related('equipment', 'technician', 'reported_by')

    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    if status_filter:
        qs = qs.filter(repair_status=status_filter)
    if priority_filter:
        qs = qs.filter(priority=priority_filter)

    paginator = Paginator(qs.order_by('-created_at'), 15)
    page = paginator.get_page(request.GET.get('page'))

    # Analytics
    total = MaintenanceRequest.objects.count()
    completed = MaintenanceRequest.objects.filter(repair_status='Completed').count()
    pending = MaintenanceRequest.objects.filter(repair_status__in=['Open', 'In Progress']).count()
    total_cost = MaintenanceRequest.objects.aggregate(s=Sum('actual_cost'))['s'] or 0

    # Group in Python to avoid MySQL timezone-table requirements.
    monthly_grouped = {}
    for created_at, actual_cost in (
        MaintenanceRequest.objects.values_list('created_at', 'actual_cost').iterator()
    ):
        if not created_at:
            continue
        created_at = timezone.localtime(created_at) if timezone.is_aware(created_at) else created_at
        key = (created_at.year, created_at.month)
        bucket = monthly_grouped.setdefault(key, {'cost': 0, 'count': 0})
        bucket['cost'] += float(actual_cost or 0)
        bucket['count'] += 1

    recent_months = sorted(monthly_grouped.keys(), reverse=True)[:6]
    recent_months.reverse()
    months_labels = [date(y, m, 1).strftime('%b %Y') for y, m in recent_months]
    months_cost = [monthly_grouped[(y, m)]['cost'] for y, m in recent_months]

    return render(request, 'maintenance/list.html', {
        'page_obj': page,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'status_choices': MaintenanceRequest.STATUS_CHOICES,
        'priority_choices': MaintenanceRequest.PRIORITY_CHOICES,
        'total': total,
        'completed': completed,
        'pending': pending,
        'total_cost': total_cost,
        'months_labels': json.dumps(months_labels),
        'months_cost': json.dumps(months_cost),
    })


@login_required
def maintenance_create(request):
    """Create a new maintenance request."""
    form = MaintenanceRequestForm()
    if request.method == 'POST':
        form = MaintenanceRequestForm(request.POST)
        if form.is_valid():
            mr = form.save(commit=False)
            mr.reported_by = request.user
            mr.save()
            # Update equipment status
            mr.equipment.status = 'Maintenance'
            mr.equipment.save()
            # Notify technicians
            from accounts.models import User
            for tech in User.objects.filter(
                role__can_manage_maintenance=True,
                role__status='Active',
                is_active=True,
            ):
                Notification.objects.create(
                    user=tech,
                    message=f'New maintenance request for {mr.equipment.name} ({mr.priority} priority).',
                    type='maintenance',
                )
            AuditLog.objects.create(
                user=request.user, action='CREATE',
                model_name='MaintenanceRequest', object_id=mr.pk,
                details=f'Maintenance request for {mr.equipment.name}'
            )
            messages.success(request, 'Maintenance request submitted.')
            return redirect('maintenance:list')
    return render(request, 'maintenance/form.html', {'form': form, 'title': 'New Maintenance Request'})


@login_required
def maintenance_detail(request, pk):
    """View and update a maintenance request."""
    mr = get_object_or_404(MaintenanceRequest, pk=pk)
    form = None

    if request.user.is_admin or request.user.is_technician or request.user.is_custodian:
        form = MaintenanceUpdateForm(instance=mr)
        if request.method == 'POST':
            form = MaintenanceUpdateForm(request.POST, instance=mr)
            if form.is_valid():
                updated = form.save()
                if updated.repair_status == 'Completed':
                    updated.equipment.status = 'Available'
                    updated.equipment.save()
                    if not updated.completion_date:
                        updated.completion_date = timezone.now().date()
                        updated.save()
                    Notification.objects.create(
                        user=updated.reported_by,
                        message=f'Maintenance for {updated.equipment.name} is now completed.',
                        type='maintenance',
                    )
                AuditLog.objects.create(
                    user=request.user, action='UPDATE',
                    model_name='MaintenanceRequest', object_id=mr.pk,
                    details=f'Updated maintenance request: status={updated.repair_status}'
                )
                messages.success(request, 'Maintenance request updated.')
                return redirect('maintenance:list')

    return render(request, 'maintenance/detail.html', {'mr': mr, 'form': form})
