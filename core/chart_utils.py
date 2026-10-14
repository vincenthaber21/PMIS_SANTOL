"""Shared helpers for monthly chart data on the dashboard."""
from datetime import date

from django.utils import timezone


def last_12_months():
    """Return (year, month) tuples and labels for the past 12 calendar months."""
    today = timezone.now().date().replace(day=1)
    y, m = today.year, today.month
    months = []
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()
    labels = [date(y, mo, 1).strftime('%b %Y') for y, mo in months]
    return months, labels


def monthly_counts(queryset, date_field, months):
    """Count records per calendar month using Python-side timezone handling."""
    grouped = {}
    for value in queryset.values_list(date_field, flat=True).iterator():
        if not value:
            continue
        if hasattr(value, 'tzinfo') and timezone.is_aware(value):
            value = timezone.localtime(value)
        grouped[(value.year, value.month)] = grouped.get((value.year, value.month), 0) + 1
    return [grouped.get((y, m), 0) for y, m in months]
