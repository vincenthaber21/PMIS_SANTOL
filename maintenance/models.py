"""Maintenance app models."""
from django.db import models
from django.conf import settings


class MaintenanceRequest(models.Model):
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Critical', 'Critical'),
    ]
    STATUS_CHOICES = [
        ('Open', 'Open'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
    ]

    equipment = models.ForeignKey(
        'equipment.Equipment', on_delete=models.CASCADE, related_name='maintenance_requests'
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='reported_maintenance'
    )
    issue_description = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='Medium')
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_maintenance'
    )
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    date_opened = models.DateField(auto_now_add=True)
    completion_date = models.DateField(null=True, blank=True)
    repair_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Open')
    technician_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"MR-{self.pk:04d}: {self.equipment.name} ({self.repair_status})"

    @property
    def repair_days(self):
        if self.completion_date:
            return (self.completion_date - self.date_opened).days
        from django.utils import timezone
        return (timezone.now().date() - self.date_opened).days
