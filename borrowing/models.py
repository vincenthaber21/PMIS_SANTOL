"""Borrowing app models."""
from django.db import models
from django.conf import settings
from django.utils import timezone


class BorrowRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Returned', 'Returned'),
        ('Overdue', 'Overdue'),
    ]

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='borrow_requests'
    )
    department = models.ForeignKey(
        'equipment.Department', on_delete=models.SET_NULL, null=True
    )
    equipment = models.ForeignKey(
        'equipment.Equipment', on_delete=models.CASCADE, related_name='borrow_requests'
    )
    quantity = models.PositiveIntegerField(default=1)
    purpose = models.TextField(blank=True)
    borrow_date = models.DateField()
    expected_return = models.DateField()
    actual_return = models.DateField(null=True, blank=True)
    approval_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_requests'
    )
    approver_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"BR-{self.pk:04d}: {self.employee} → {self.equipment.name}"

    @property
    def is_overdue(self):
        if self.approval_status == 'Approved' and self.actual_return is None:
            return timezone.now().date() > self.expected_return
        return False

    @property
    def days_borrowed(self):
        end = self.actual_return or timezone.now().date()
        return (end - self.borrow_date).days

    def check_and_flag_overdue(self):
        """Flag overdue items and update equipment status."""
        if self.is_overdue and self.approval_status != 'Overdue':
            self.approval_status = 'Overdue'
            self.save()
