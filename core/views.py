"""Core views: dashboard, audit trail, notifications, search."""
import json
from datetime import datetime, date, timedelta

from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from .decorators import insights_login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone
from equipment.models import Equipment, PropertyStatus
from equipment.views import _filter_equipment_for_user, _filter_equipment_for_dashboard
from .chart_utils import last_12_months, monthly_counts
from .models import AuditLog, Notification

User = get_user_model()


def _resolve_period(request):
    """Resolve the dashboard time filter from the query string.

    Returns a dict with the active period, the [start, end) date bounds (None
    for "all time"), a human label, and the default values used to pre-fill the
    week / month / year pickers.
    """
    today = timezone.localdate()
    period = request.GET.get('period', 'all')
    if period not in ('all', 'week', 'month', 'year'):
        period = 'all'

    # Default picker values (used even when a period is inactive).
    iso = today.isocalendar()
    default_week = f'{iso.year}-W{iso.week:02d}'
    default_month = f'{today.year}-{today.month:02d}'
    default_year = today.year

    start = end = None
    label = 'All time'

    if period == 'week':
        raw = request.GET.get('week', '')
        start = None
        if raw:
            try:
                y_str, w_str = raw.split('-W')
                start = date.fromisocalendar(int(y_str), int(w_str), 1)
            except (ValueError, TypeError):
                start = None
        if start is None:
            start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
        wiso = start.isocalendar()
        default_week = f'{wiso.year}-W{wiso.week:02d}'
        label = f'Week of {start.strftime("%b %d, %Y")}'

    elif period == 'month':
        raw = request.GET.get('month', '')
        start = None
        if raw:
            try:
                y_str, m_str = raw.split('-')
                start = date(int(y_str), int(m_str), 1)
            except (ValueError, TypeError):
                start = None
        if start is None:
            start = today.replace(day=1)
        end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
        default_month = f'{start.year}-{start.month:02d}'
        label = start.strftime('%B %Y')

    elif period == 'year':
        raw = request.GET.get('year', '')
        try:
            y = int(raw)
        except (ValueError, TypeError):
            y = today.year
        start = date(y, 1, 1)
        end = date(y + 1, 1, 1)
        default_year = y
        label = str(y)

    return {
        'period': period,
        'start': start,
        'end': end,
        'label': label,
        'default_week': default_week,
        'default_month': default_month,
        'default_year': default_year,
    }


def _daily_registration_counts(queryset, start, end):
    """Map of {date: count} of equipment registered per day in [start, end)."""
    grouped = {}
    for created_at in queryset.values_list('created_at', flat=True).iterator():
        if not created_at:
            continue
        day = timezone.localtime(created_at).date() if timezone.is_aware(created_at) else created_at.date()
        if start <= day < end:
            grouped[day] = grouped.get(day, 0) + 1
    return grouped


def _registration_trend(queryset, period, start):
    """Build the trend chart series adapted to the active period.

    Returns (labels, values, dataset_label). "All time" shows the cumulative
    total over the last 12 months; filtered periods show new registrations per
    day (week / month) or per month (year).
    """
    if period == 'week':
        days = [start + timedelta(days=i) for i in range(7)]
        counts = _daily_registration_counts(queryset, start, start + timedelta(days=7))
        labels = [d.strftime('%a %d') for d in days]
        values = [counts.get(d, 0) for d in days]
        return labels, values, 'New Registrations'

    if period == 'month':
        end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
        num_days = (end - start).days
        days = [start + timedelta(days=i) for i in range(num_days)]
        counts = _daily_registration_counts(queryset, start, end)
        labels = [d.strftime('%d') for d in days]
        values = [counts.get(d, 0) for d in days]
        return labels, values, 'New Registrations'

    if period == 'year':
        months = [(start.year, m) for m in range(1, 13)]
        labels = [date(y, m, 1).strftime('%b') for y, m in months]
        values = monthly_counts(queryset, 'created_at', months)
        return labels, values, 'New Registrations'

    # All time: cumulative growth over the last 12 months.
    months, labels = last_12_months()
    monthly_acquisitions = monthly_counts(queryset, 'created_at', months)
    first_month_start = timezone.make_aware(datetime(months[0][0], months[0][1], 1))
    running = queryset.filter(created_at__lt=first_month_start).count()
    cumulative = []
    for count in monthly_acquisitions:
        running += count
        cumulative.append(running)
    return labels, cumulative, 'Total Registered'


@login_required
def dashboard(request):
    """Main dashboard with KPIs and charts, scoped by an optional time filter."""
    flt = _resolve_period(request)

    equipment_qs = _filter_equipment_for_dashboard(Equipment.objects.all(), request.user)
    if flt['start'] is not None:
        start_dt = timezone.make_aware(datetime.combine(flt['start'], datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(flt['end'], datetime.min.time()))
        equipment_qs = equipment_qs.filter(created_at__gte=start_dt, created_at__lt=end_dt)

    total_equipment = equipment_qs.count()
    available = equipment_qs.filter(status='Available').count()
    retired = equipment_qs.filter(status='Retired').count()

    property_status_counts = {
        row['property_status__name']: row['count']
        for row in equipment_qs.values('property_status__name').annotate(count=Count('pk'))
    }
    total_property = total_equipment
    working = property_status_counts.get('Working', 0)
    # Prefer Disposed (current DB status); include legacy Condemned if any remain.
    disposed = (
        property_status_counts.get(PropertyStatus.DISPOSE_STATUS, 0)
        + property_status_counts.get('Condemned', 0)
    )
    unserviceable = property_status_counts.get('Unserviceable', 0)

    property_status_data = {
        'labels': ['Working', 'Disposed', 'Unserviceable'],
        'data': [working, disposed, unserviceable],
    }

    trend_labels, trend_values, trend_dataset_label = _registration_trend(
        equipment_qs, flt['period'], flt['start']
    )

    office_data = list(
        equipment_qs.values('department__name')
        .annotate(count=Count('pk'))
        .order_by('-count')
    )
    office_chart = {
        'labels': [row['department__name'] or 'Unassigned' for row in office_data],
        'data': [row['count'] for row in office_data],
    }

    category_data = list(
        equipment_qs.values('category__name')
        .annotate(count=Count('pk'))
        .order_by('-count')
    )
    category_chart = {
        'labels': [row['category__name'] or 'Uncategorized' for row in category_data],
        'data': [row['count'] for row in category_data],
    }

    status_links = {
        row['name']: row['pk']
        for row in PropertyStatus.objects.filter(
            name__in=['Working', PropertyStatus.DISPOSE_STATUS, 'Unserviceable'],
        ).values('name', 'pk')
    }

    context = {
        'total_equipment': total_equipment,
        'available': available,
        'retired': retired,
        'total_property': total_property,
        'working': working,
        'disposed': disposed,
        'unserviceable': unserviceable,
        'status_links': status_links,
        'property_status_data': json.dumps(property_status_data),
        'trend_labels': json.dumps(trend_labels),
        'trend_values': json.dumps(trend_values),
        'trend_dataset_label': trend_dataset_label,
        'office_chart': json.dumps(office_chart),
        'category_chart': json.dumps(category_chart),
        # Filter state
        'period': flt['period'],
        'period_label': flt['label'],
        'period_value_week': flt['default_week'],
        'period_value_month': flt['default_month'],
        'period_value_year': flt['default_year'],
    }
    return render(request, 'core/dashboard.html', context)


@insights_login_required
def audit_trail(request):
    """View audit log entries."""
    logs = AuditLog.objects.select_related('user').order_by('-timestamp')
    model_filter = request.GET.get('model', '')
    action_filter = request.GET.get('action', '')
    if model_filter:
        logs = logs.filter(model_name=model_filter)
    if action_filter:
        logs = logs.filter(action=action_filter)

    from django.core.paginator import Paginator
    paginator = Paginator(logs, 20)
    page = paginator.get_page(request.GET.get('page'))

    models_list = AuditLog.objects.values_list('model_name', flat=True).distinct()
    return render(request, 'core/audit_trail.html', {
        'page_obj': page,
        'model_filter': model_filter,
        'action_filter': action_filter,
        'models_list': models_list,
        'action_choices': AuditLog.ACTION_CHOICES,
    })


@login_required
def notifications_view(request):
    """List notifications — all users for insights roles, personal inbox for others."""
    show_all = request.user.can_access_insights

    if show_all:
        notes = Notification.objects.select_related('user', 'user__role').order_by('-created_at')
    else:
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        notes = Notification.objects.filter(user=request.user).order_by('-created_at')

    user_filter = request.GET.get('user', '')
    type_filter = request.GET.get('type', '')
    read_filter = request.GET.get('read', '')

    if show_all:
        if user_filter:
            notes = notes.filter(user_id=user_filter)
        if type_filter:
            notes = notes.filter(type=type_filter)
        if read_filter == 'read':
            notes = notes.filter(is_read=True)
        elif read_filter == 'unread':
            notes = notes.filter(is_read=False)

    paginator = Paginator(notes, 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page,
        'show_all': show_all,
        'user_filter': user_filter,
        'type_filter': type_filter,
        'read_filter': read_filter,
        'type_choices': Notification.TYPE_CHOICES,
    }
    if show_all:
        context['users_list'] = (
            User.objects.filter(notifications__isnull=False)
            .distinct()
            .order_by('first_name', 'last_name', 'username')
        )
        context['unread_total'] = Notification.objects.filter(is_read=False).count()
    return render(request, 'core/notifications.html', context)


@login_required
def global_search(request):
    """Global search across equipment."""
    q = request.GET.get('q', '').strip()
    results = {'equipment': []}
    if q:
        qs = Equipment.objects.filter(
            Q(name__icontains=q) |
            Q(property_number__icontains=q) |
            Q(brand__icontains=q)
        )
        results['equipment'] = _filter_equipment_for_user(qs, request.user)
    return render(request, 'core/search_results.html', {'q': q, 'results': results})
