"""
Create a full database ZIP if the day-countdown schedule has reached 0.

Usage (Windows Task Scheduler / cron — run daily or every few hours):
  python manage.py run_scheduled_database_backup
"""
from django.core.management.base import BaseCommand

from core.admin_export import run_scheduled_database_backup
from core.models import AutoDatabaseDownloadSchedule


class Command(BaseCommand):
    help = 'Run automatic database ZIP backup when the day countdown reaches 0.'

    def handle(self, *args, **options):
        schedule = AutoDatabaseDownloadSchedule.get_solo()
        if not schedule.is_enabled:
            self.stdout.write('Automatic download schedule is OFF — nothing to do.')
            return

        remaining = schedule.days_remaining
        target = schedule.target_date
        self.stdout.write(
            f'Countdown: {schedule.countdown_days} days from {schedule.start_date} '
            f'→ {remaining} day(s) left (due {target})'
        )

        if not schedule.is_due():
            self.stdout.write('Not due yet — no backup created.')
            return

        try:
            record, _content = run_scheduled_database_backup(user=None)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Backup failed: {exc}'))
            raise

        if record is None:
            self.stdout.write('Not due / already ran — no backup created.')
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Automatic backup saved: {record.filename} '
                f'({record.file_size_display}, {record.object_count} objects). '
                f'Countdown restarted for {schedule.countdown_days} days.'
            )
        )
