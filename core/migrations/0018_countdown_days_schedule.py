# Generated manually for countdown-based auto download schedule

from django.db import migrations, models
from django.utils import timezone


def forwards_countdown(apps, schema_editor):
    Schedule = apps.get_model('core', 'AutoDatabaseDownloadSchedule')
    today = timezone.localdate()
    for row in Schedule.objects.all():
        if getattr(row, 'countdown_days', None) in (None, 0):
            row.countdown_days = 100
        if not getattr(row, 'start_date', None):
            row.start_date = today
        row.save(update_fields=['countdown_days', 'start_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_auto_download_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='autodatabasedownloadschedule',
            name='countdown_days',
            field=models.PositiveIntegerField(
                default=100,
                help_text='How many days from the start date until automatic download (e.g. 100).',
            ),
        ),
        migrations.AddField(
            model_name='autodatabasedownloadschedule',
            name='start_date',
            field=models.DateField(
                blank=True,
                help_text='Date the countdown started (usually today when you save).',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='autodatabasedownloadschedule',
            name='is_enabled',
            field=models.BooleanField(
                default=True,
                help_text='When enabled, PMS creates a ZIP backup when the day counter reaches 0.',
            ),
        ),
        migrations.RunPython(forwards_countdown, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='autodatabasedownloadschedule',
            name='day',
        ),
        migrations.RemoveField(
            model_name='autodatabasedownloadschedule',
            name='hour',
        ),
        migrations.RemoveField(
            model_name='autodatabasedownloadschedule',
            name='minute',
        ),
        migrations.RemoveField(
            model_name='autodatabasedownloadschedule',
            name='month',
        ),
    ]
