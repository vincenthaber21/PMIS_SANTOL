"""Admin views for downloading and importing a full database dump (JSON/ZIP)."""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO, StringIO

from django.apps import apps
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect

# Local business apps + auth groups (needed for roles/permissions restore).
EXPORT_APPS = (
    'accounts',
    'equipment',
    'borrowing',
    'maintenance',
    'reports',
    'core',
    'auth',
)

# Skip noisy / environment-specific tables from auth.
EXCLUDE_MODELS = (
    'auth.permission',  # rebuilt from code; keep Group via dump
    'contenttypes.contenttype',
    'sessions.session',
    'admin.logentry',
)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


def _is_superuser(user) -> bool:
    return bool(user and user.is_authenticated and user.is_superuser)


def get_export_model_stats():
    """Return [{app, model, label, count}, ...] for apps included in the dump."""
    rows = []
    for app_label in EXPORT_APPS:
        try:
            app_config = apps.get_app_config(app_label)
        except LookupError:
            continue
        for model in app_config.get_models():
            model_key = f'{model._meta.app_label}.{model._meta.model_name}'
            if model_key.lower() == 'auth.permission':
                continue
            try:
                count = model.objects.count()
            except Exception:
                count = 0
            rows.append({
                'app': app_label,
                'model': model._meta.model_name,
                'label': model._meta.verbose_name_plural.title(),
                'count': count,
            })
    return rows


def build_database_dump_json() -> str:
    """Serialize all export apps to a Django dumpdata JSON string."""
    buffer = StringIO()
    call_command(
        'dumpdata',
        *EXPORT_APPS,
        exclude=list(EXCLUDE_MODELS),
        indent=2,
        stdout=buffer,
        # Use numeric FKs so import remapping stays reliable across databases.
        natural_foreign=False,
        natural_primary=False,
    )
    return buffer.getvalue()


def build_database_dump_zip(json_payload: str, stamp: str) -> bytes:
    """Wrap the JSON dump in a zip archive."""
    mem = BytesIO()
    with zipfile.ZipFile(mem, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'pms-database-{stamp}.json', json_payload)
        zf.writestr(
            'README.txt',
            (
                'PMS full database export\n'
                f'Generated: {stamp}\n'
                'Apps: ' + ', '.join(EXPORT_APPS) + '\n\n'
                'Restore via Admin:\n'
                '  /admin/download-database/  →  Import section\n\n'
                'Or via CLI (migrations applied):\n'
                '  python manage.py loaddata pms-database-YYYYMMDD.json\n\n'
                'Admin import merges data (adds/updates) and does not wipe rows.\n'
                'Note: Uploaded media files (logos, avatars, QR images) are NOT included.\n'
                'User password hashes ARE included — treat this file as confidential.\n'
            ),
        )
    return mem.getvalue()


def extract_fixture_bytes(uploaded_file) -> tuple[bytes, str]:
    """
    Read an uploaded .json or .zip and return (fixture_bytes, source_label).
    """
    name = (uploaded_file.name or 'upload').lower()
    raw = uploaded_file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f'File is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).'
        )
    if not raw:
        raise ValueError('Uploaded file is empty.')

    if name.endswith('.zip'):
        try:
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                json_names = [
                    n for n in zf.namelist()
                    if n.lower().endswith('.json')
                    and not n.startswith('__MACOSX')
                    and not os.path.basename(n).startswith('.')
                ]
                if not json_names:
                    raise ValueError('ZIP archive contains no .json fixture file.')
                preferred = [
                    n for n in json_names if 'pms-database' in n.lower()
                ]
                chosen = preferred[0] if preferred else json_names[0]
                return zf.read(chosen), f'{uploaded_file.name} → {chosen}'
        except zipfile.BadZipFile as exc:
            raise ValueError('Invalid ZIP file.') from exc

    if name.endswith('.json'):
        return raw, uploaded_file.name or 'upload.json'

    raise ValueError('Upload a .json or .zip file exported from this admin.')


def validate_fixture(payload: bytes) -> tuple[list, int]:
    """Parse and lightly validate a Django fixture. Returns (objects, count)."""
    try:
        text = payload.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('Fixture must be UTF-8 JSON.') from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON: {exc}') from exc
    if not isinstance(data, list):
        raise ValueError('Fixture must be a JSON array of Django objects.')
    for i, item in enumerate(data[:5]):
        if not isinstance(item, dict) or 'model' not in item:
            raise ValueError(
                f'Invalid fixture entry at index {i}: '
                'expected objects with a "model" key.'
            )
    return data, len(data)


def _unique_fields(model):
    """Non-PK fields with unique=True (single-column uniqueness)."""
    return [
        f for f in model._meta.local_fields
        if getattr(f, 'unique', False) and not f.primary_key
    ]


def normalize_fixture_objects(data: list) -> list:
    """Fix known legacy values and drop in-fixture unique duplicates."""
    normalized = []
    seen_unique = {}  # (model_label, field_name, value) -> index in normalized

    for item in data:
        if not isinstance(item, dict) or 'model' not in item:
            normalized.append(item)
            continue

        model_label = item['model']
        fields = dict(item.get('fields') or {})

        # Legacy rename from migration 0021 (Dispose → Disposed).
        if (
            model_label.lower() == 'equipment.propertystatus'
            and isinstance(fields.get('name'), str)
            and fields['name'].strip().lower() == 'dispose'
        ):
            fields['name'] = 'Disposed'

        item = {**item, 'fields': fields}

        # Drop later duplicates of the same unique field value within the fixture.
        try:
            model = apps.get_model(model_label)
        except LookupError:
            normalized.append(item)
            continue

        duplicate_of = None
        for field in _unique_fields(model):
            value = fields.get(field.attname, fields.get(field.name))
            if value is None:
                continue
            key = (model_label.lower(), field.name, value)
            if key in seen_unique:
                duplicate_of = seen_unique[key]
                break

        if duplicate_of is not None:
            # Prefer an entry that already carries a primary key.
            existing = normalized[duplicate_of]
            if existing.get('pk') is None and item.get('pk') is not None:
                normalized[duplicate_of] = item
            continue

        for field in _unique_fields(model):
            value = fields.get(field.attname, fields.get(field.name))
            if value is None:
                continue
            seen_unique[(model_label.lower(), field.name, value)] = len(normalized)

        normalized.append(item)

    return normalized


def resolve_unique_conflicts_for_load(data: list) -> list:
    """
    Keep existing rows: if a fixture object shares a unique value with a DB row
    under a different PK (e.g. par_no / Disposed), remap fixture FKs onto that
    existing PK. If that PK is already represented in the fixture, drop the
    duplicate fixture object. Never deletes database rows.
    """
    pk_remap = {}  # (model_label_lower, fixture_pk) -> existing_pk
    drop_indexes = set()

    # pk -> first index for each model in the fixture
    fixture_pk_index = {}
    for i, item in enumerate(data):
        if not isinstance(item, dict) or 'model' not in item:
            continue
        pk = item.get('pk')
        if pk is None:
            continue
        label = item['model'].lower()
        fixture_pk_index.setdefault(label, {}).setdefault(pk, i)

    for i, item in enumerate(data):
        if not isinstance(item, dict) or 'model' not in item:
            continue
        model_label = item['model']
        label = model_label.lower()
        fixture_pk = item.get('pk')
        fields = item.get('fields') or {}
        try:
            model = apps.get_model(model_label)
        except LookupError:
            continue

        for field in _unique_fields(model):
            value = fields.get(field.attname, fields.get(field.name))
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                fields[field.name] = value
                item['fields'] = fields

            existing = (
                model.objects.filter(**{field.name: value})
                .exclude(pk=fixture_pk)
                .first()
            )
            if existing is None:
                continue

            if fixture_pk is None:
                item['pk'] = existing.pk
                break

            if existing.pk == fixture_pk:
                break

            pk_remap[(label, fixture_pk)] = existing.pk
            # Another fixture row already owns this PK — keep that one, skip ours.
            if existing.pk in fixture_pk_index.get(label, {}):
                drop_indexes.add(i)
            else:
                # Free the old pk slot in the index and claim the existing pk.
                if fixture_pk_index.get(label, {}).get(fixture_pk) == i:
                    fixture_pk_index[label].pop(fixture_pk, None)
                item['pk'] = existing.pk
                fixture_pk_index.setdefault(label, {})[existing.pk] = i
            break

    if pk_remap:
        for item in data:
            if not isinstance(item, dict) or 'model' not in item:
                continue
            try:
                model = apps.get_model(item['model'])
            except LookupError:
                continue
            fields = item.get('fields') or {}
            changed = False
            for field in model._meta.fields:
                if not field.is_relation or field.many_to_many:
                    continue
                rel_model = field.related_model
                if rel_model is None:
                    continue
                rel_label = (
                    f'{rel_model._meta.app_label}.{rel_model._meta.model_name}'
                ).lower()
                for store_key in (field.name, field.attname):
                    if store_key not in fields:
                        continue
                    raw = fields[store_key]
                    if raw is None or isinstance(raw, (list, dict)):
                        continue
                    mapped = pk_remap.get((rel_label, raw))
                    if mapped is not None and mapped != raw:
                        fields[store_key] = mapped
                        changed = True
            if changed:
                item['fields'] = fields

    if not drop_indexes:
        return data
    return [item for i, item in enumerate(data) if i not in drop_indexes]


def _user_fk_fields(model):
    """Yield concrete FK fields on model that point at accounts.User."""
    for field in model._meta.fields:
        if not field.is_relation or field.many_to_many:
            continue
        rel = field.related_model
        if rel is None:
            continue
        if (
            rel._meta.app_label == 'accounts'
            and rel._meta.model_name == 'user'
        ):
            yield field


def _resolve_user_ref(raw, *, username_to_pk, pk_to_pk, User):
    """
    Resolve a fixture user reference (pk int, natural key [username], or null)
    to a concrete user primary key, or None if unknown.
    """
    if raw is None:
        return None

    # Natural key form from dumpdata natural_foreign=True: ["username"]
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        username = raw[0]
        if username in username_to_pk:
            return username_to_pk[username]
        existing = User.objects.filter(username=username).first()
        return existing.pk if existing else None

    if isinstance(raw, dict):
        return None

    # Numeric / string PK
    try:
        pk = int(raw)
    except (TypeError, ValueError):
        # Bare username string
        if isinstance(raw, str) and raw in username_to_pk:
            return username_to_pk[raw]
        existing = User.objects.filter(username=raw).first() if isinstance(raw, str) else None
        return existing.pk if existing else None

    if pk in pk_to_pk:
        return pk_to_pk[pk]
    if User.objects.filter(pk=pk).exists():
        return pk
    return None


def preserve_existing_users(data: list) -> list:
    """
    Never overwrite or remove users already in the database.

    Also converts natural-key user FKs (e.g. ["jane"]) to real PKs and remaps
    references after skipping/renumbering fixture users, so required fields
    like ICS.received_by never become null.
    """
    try:
        User = apps.get_model('accounts', 'user')
    except LookupError:
        return data

    user_label = 'accounts.user'
    pk_remap = {}  # fixture_pk -> final pk used in DB
    username_to_pk = {}
    drop_indexes = set()
    max_pk = User.objects.order_by('-pk').values_list('pk', flat=True).first() or 0
    next_pk = max_pk + 1

    # Seed username map from local users first.
    for pk, username in User.objects.values_list('pk', 'username'):
        if username:
            username_to_pk[username] = pk

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        if (item.get('model') or '').lower() != user_label:
            continue

        fields = item.get('fields') or {}
        fixture_pk = item.get('pk')
        username = fields.get('username')
        email = (fields.get('email') or '').strip()

        match = None
        if username:
            match = User.objects.filter(username=username).first()
        if match is None and email:
            match = User.objects.filter(email__iexact=email).first()

        if match is not None:
            if fixture_pk is not None:
                pk_remap[fixture_pk] = match.pk
            if username:
                username_to_pk[username] = match.pk
            # Prefer local username for lookups when email matched a different name.
            if match.username:
                username_to_pk[match.username] = match.pk
            drop_indexes.add(i)
            continue

        by_pk = (
            User.objects.filter(pk=fixture_pk).first()
            if fixture_pk is not None
            else None
        )
        if by_pk is not None:
            while (
                User.objects.filter(pk=next_pk).exists()
                or next_pk in pk_remap.values()
            ):
                next_pk += 1
            pk_remap[fixture_pk] = next_pk
            item['pk'] = next_pk
            if username:
                username_to_pk[username] = next_pk
            next_pk += 1
            continue

        # Brand-new user kept as-is.
        final_pk = fixture_pk
        if final_pk is None:
            while (
                User.objects.filter(pk=next_pk).exists()
                or next_pk in pk_remap.values()
            ):
                next_pk += 1
            final_pk = next_pk
            item['pk'] = final_pk
            next_pk += 1
        if fixture_pk is not None:
            pk_remap[fixture_pk] = final_pk
        if username and final_pk is not None:
            username_to_pk[username] = final_pk

    fallback_pk = (
        User.objects.filter(is_superuser=True).order_by('pk').values_list('pk', flat=True).first()
        or User.objects.order_by('pk').values_list('pk', flat=True).first()
    )

    for item in data:
        if not isinstance(item, dict) or 'model' not in item:
            continue
        try:
            model = apps.get_model(item['model'])
        except LookupError:
            continue
        fields = item.get('fields') or {}
        changed = False

        for field in _user_fk_fields(model):
            key_missing = field.name not in fields and field.attname not in fields
            if field.name in fields:
                raw = fields[field.name]
            elif field.attname in fields:
                raw = fields[field.attname]
            else:
                raw = None

            resolved = _resolve_user_ref(
                raw,
                username_to_pk=username_to_pk,
                pk_to_pk=pk_remap,
                User=User,
            )
            if resolved is None and not field.null:
                resolved = fallback_pk
            if key_missing and resolved is None and field.null:
                continue

            if field.attname in fields and field.attname != field.name:
                del fields[field.attname]
            if fields.get(field.name) != resolved or isinstance(raw, (list, tuple)):
                fields[field.name] = resolved
                changed = True

        for field in model._meta.many_to_many:
            rel = field.related_model
            if rel is None:
                continue
            if not (
                rel._meta.app_label == 'accounts'
                and rel._meta.model_name == 'user'
            ):
                continue
            if field.name not in fields or not isinstance(fields[field.name], list):
                continue
            new_list = []
            for raw in fields[field.name]:
                if isinstance(raw, (list, tuple)):
                    resolved = _resolve_user_ref(
                        raw,
                        username_to_pk=username_to_pk,
                        pk_to_pk=pk_remap,
                        User=User,
                    )
                    new_list.append(resolved if resolved is not None else raw)
                else:
                    new_list.append(pk_remap.get(raw, raw))
            if new_list != fields[field.name]:
                fields[field.name] = new_list
                changed = True

        if changed:
            item['fields'] = fields

    if not drop_indexes:
        return data
    return [item for i, item in enumerate(data) if i not in drop_indexes]


def prepare_fixture_for_load(data: list) -> tuple[list, bytes]:
    """Normalize fixture, preserve users, remap unique clashes, return JSON."""
    prepared = normalize_fixture_objects(data)
    prepared = preserve_existing_users(prepared)
    prepared = resolve_unique_conflicts_for_load(prepared)
    payload = json.dumps(prepared, indent=2, ensure_ascii=False).encode('utf-8')
    return prepared, payload


def _set_foreign_key_checks(enabled: bool):
    """Temporarily relax FK checks (used only if wipe helpers are called)."""
    from django.db import connection

    with connection.cursor() as cursor:
        if connection.vendor == 'mysql':
            cursor.execute(
                'SET FOREIGN_KEY_CHECKS=%s',
                [1 if enabled else 0],
            )
        elif connection.vendor == 'sqlite':
            cursor.execute(
                'PRAGMA foreign_keys=%s' % ('ON' if enabled else 'OFF')
            )


def clear_export_app_data(preserve_user_id=None):
    """Delete export-app rows, but never delete any user accounts.

    preserve_user_id is kept for call-site compatibility; all users are retained.
    """
    models = []
    for app_label in EXPORT_APPS:
        try:
            app_config = apps.get_app_config(app_label)
        except LookupError:
            continue
        for model in app_config.get_models():
            if (
                model._meta.app_label == 'auth'
                and model._meta.model_name == 'permission'
            ):
                continue
            # Never wipe user accounts.
            if (
                model._meta.app_label == 'accounts'
                and model._meta.model_name == 'user'
            ):
                continue
            models.append(model)

    _set_foreign_key_checks(False)
    try:
        for model in reversed(models):
            model.objects.all().delete()
    finally:
        _set_foreign_key_checks(True)


def load_fixture_bytes(payload: bytes) -> str:
    """Write fixture to a temp file and run loaddata. Returns command output."""
    fd, path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'wb') as tmp:
            tmp.write(payload)
        out = StringIO()
        err = StringIO()
        call_command('loaddata', path, stdout=out, stderr=err, verbosity=1)
        combined = (out.getvalue() + err.getvalue()).strip()
        return combined or 'Fixture loaded successfully.'
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _audit(user, action_label: str, details: str, object_id: str = ''):
    try:
        from core.models import AuditLog
        AuditLog.objects.create(
            user=user,
            action='CREATE' if 'export' in action_label.lower() else 'UPDATE',
            model_name=action_label,
            object_id=object_id or '-',
            details=details,
        )
    except Exception:
        pass


def _count_fixture_objects(payload: str) -> int:
    try:
        data = json.loads(payload)
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def save_database_download(
    user,
    export_format: str,
    stamp: str,
    payload: str,
    *,
    year=None,
    quarter=None,
    notes='',
):
    """Persist export to media and return (DatabaseDownload, file_bytes)."""
    from core.models import DatabaseDownload

    quarter_tag = ''
    if year and quarter:
        quarter_tag = f'-Q{quarter}-{year}'

    if export_format == 'zip':
        content = build_database_dump_zip(payload, stamp)
        filename = f'pms-database{quarter_tag}-{stamp}.zip'
    else:
        content = payload.encode('utf-8')
        filename = f'pms-database{quarter_tag}-{stamp}.json'

    if not notes:
        if year and quarter:
            notes = f'Auto-saved Q{quarter} {year} {export_format.upper()} export'
        else:
            notes = f'Auto-saved {export_format.upper()} export'

    record = DatabaseDownload(
        filename=filename,
        export_format=export_format,
        file_size=len(content),
        object_count=_count_fixture_objects(payload),
        year=year,
        quarter=quarter,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
        notes=notes,
    )
    record.file.save(filename, ContentFile(content), save=True)
    return record, content


def _parse_quarter_params(request):
    """Return (year, quarter) from GET/POST or (None, None)."""
    raw_year = request.POST.get('year') or request.GET.get('year')
    raw_quarter = request.POST.get('quarter') or request.GET.get('quarter')
    if not raw_year or not raw_quarter:
        return None, None
    try:
        year = int(raw_year)
        quarter = int(raw_quarter)
    except (TypeError, ValueError):
        return None, None
    if year < 2000 or year > 2100 or quarter not in (1, 2, 3, 4):
        return None, None
    return year, quarter


def _page_context(request):
    from core.models import (
        AutoDatabaseDownloadSchedule,
        DatabaseDownload,
        QuarterlyDatabaseBackup,
    )

    stats = get_export_model_stats()
    recent = list(
        DatabaseDownload.objects.select_related('created_by')[:8]
    )
    quarterly = list(
        QuarterlyDatabaseBackup.objects.select_related(
            'download', 'created_by'
        )[:12]
    )
    schedule = AutoDatabaseDownloadSchedule.get_solo()
    # Page-load auto ZIP only when ?auto=1 (quarter form is the main path).
    auto_download = request.GET.get('auto') == '1'
    current_year = QuarterlyDatabaseBackup.current_year()
    year_choices = list(range(current_year + 1, current_year - 6, -1))
    return {
        **admin.site.each_context(request),
        'title': 'Database import / export',
        'stats': stats,
        'total_rows': sum(row['count'] for row in stats),
        'export_apps': EXPORT_APPS,
        'json_url': reverse('admin:download_database_json'),
        'zip_url': reverse('admin:download_database_zip'),
        'import_url': reverse('admin:import_database'),
        'history_url': reverse('admin:download_database_history'),
        'quarter_url': reverse('admin:download_database_quarter'),
        'schedule_url': reverse('admin:download_database_schedule'),
        'recent_downloads': recent,
        'quarterly_backups': quarterly,
        'auto_download': auto_download,
        'quarter_choices': QuarterlyDatabaseBackup.QUARTER_CHOICES,
        'year_choices': year_choices,
        'default_year': current_year,
        'default_quarter': QuarterlyDatabaseBackup.current_quarter(),
        'schedule': schedule,
        'next_run': schedule.next_run_datetime() if schedule.is_enabled else None,
        'days_remaining': schedule.days_remaining,
        'target_date': schedule.target_date,
        'schedule_due': schedule.is_due(),
        'opts': None,
        'has_permission': True,
    }


def run_scheduled_database_backup(user=None):
    """
    Create a ZIP backup for the current schedule if due.
    Returns (download_record, content_bytes) or (None, None).
    """
    from core.models import (
        AutoDatabaseDownloadSchedule,
        QuarterlyDatabaseBackup,
    )

    schedule = AutoDatabaseDownloadSchedule.get_solo()
    if not schedule.is_due():
        return None, None

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    year = QuarterlyDatabaseBackup.current_year()
    quarter = QuarterlyDatabaseBackup.current_quarter()
    payload = build_database_dump_json()
    json.loads(payload)

    notes = (
        f'Automatic backup — scheduled for {schedule.schedule_display}'
    )
    record, content = save_database_download(
        user,
        'zip',
        stamp,
        payload,
        year=year,
        quarter=quarter,
        notes=notes,
    )
    QuarterlyDatabaseBackup.objects.create(
        year=year,
        quarter=quarter,
        download=record,
        created_by=user if getattr(user, 'is_authenticated', False) else None,
        notes=notes,
    )
    schedule.mark_run(record)
    _audit(
        user,
        'DatabaseExport',
        f'Automatic scheduled ZIP ({schedule.schedule_display})',
        stamp,
    )
    return record, content


class DownloadDatabaseView(View):
    """Admin page for export downloads and import upload form."""

    template_name = 'admin/core/download_database.html'

    @method_decorator(staff_member_required)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can import or export the full database.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        # If schedule is due when a superuser opens the page, create backup
        # and offer the ZIP download once.
        try:
            record, content = run_scheduled_database_backup(request.user)
        except Exception:
            record, content = None, None

        context = _page_context(request)
        if record and content and request.GET.get('nosched') != '1':
            context['auto_download'] = True
            context['scheduled_download_ready'] = True
            context['zip_url'] = reverse(
                'admin:download_database_saved_file', args=[record.pk]
            )
            messages.success(
                request,
                (
                    f'Automatic schedule is due — saved backup '
                    f'{record.filename}. Download starting…'
                ),
            )
        return render(request, self.template_name, context)


class AutoDownloadScheduleView(View):
    """Save month / day / time for automatic database downloads."""

    @method_decorator(staff_member_required)
    @method_decorator(csrf_protect)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can change the automatic download schedule.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return redirect(reverse('admin:download_database') + '?auto=0')

    def post(self, request):
        from django.utils import timezone

        from core.models import AutoDatabaseDownloadSchedule

        schedule = AutoDatabaseDownloadSchedule.get_solo()
        try:
            days = int(request.POST.get('countdown_days', schedule.countdown_days))
        except (TypeError, ValueError):
            messages.error(request, 'Enter a valid number of days (e.g. 100).')
            return redirect(reverse('admin:download_database') + '?auto=0')

        if days < 1 or days > 3650:
            messages.error(request, 'Days must be between 1 and 3650.')
            return redirect(reverse('admin:download_database') + '?auto=0')

        restart = request.POST.get('restart_countdown') == '1'
        schedule.countdown_days = days
        schedule.is_enabled = request.POST.get('is_enabled') == '1'
        schedule.updated_by = request.user
        if restart or schedule.start_date is None:
            schedule.start_date = timezone.localdate()
        schedule.save()

        if schedule.is_enabled:
            remaining = schedule.days_remaining
            target = schedule.target_date
            messages.success(
                request,
                (
                    f'Countdown saved: {days} days starting '
                    f'{schedule.start_date:%B %d, %Y}. '
                    f'{remaining} day(s) left — automatic download on '
                    f'{target:%B %d, %Y}.'
                ),
            )
        else:
            messages.warning(
                request,
                'Schedule saved but automatic download is turned OFF.',
            )
        return redirect(reverse('admin:download_database') + '?auto=0')


class QuarterlyDatabaseBackupView(View):
    """
    Accept year + quarter, create QuarterlyDatabaseBackup, then stream ZIP.
    """

    @method_decorator(staff_member_required)
    @method_decorator(csrf_protect)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can create quarterly database backups.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return redirect(reverse('admin:download_database') + '?auto=0')

    def post(self, request):
        from core.models import QuarterlyDatabaseBackup

        year, quarter = _parse_quarter_params(request)
        if year is None:
            messages.error(
                request,
                'Choose a valid year and quarter (Q1–Q4) to download.',
            )
            return redirect(reverse('admin:download_database') + '?auto=0')

        notes = (request.POST.get('notes') or '').strip()[:255]
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')

        try:
            payload = build_database_dump_json()
            json.loads(payload)
        except Exception as exc:
            messages.error(request, f'Database export failed: {exc}')
            return redirect(reverse('admin:download_database') + '?auto=0')

        try:
            record, content = save_database_download(
                request.user,
                'zip',
                stamp,
                payload,
                year=year,
                quarter=quarter,
                notes=notes or f'Quarterly full backup Q{quarter} {year}',
            )
            QuarterlyDatabaseBackup.objects.create(
                year=year,
                quarter=quarter,
                download=record,
                created_by=request.user,
                notes=notes,
            )
        except Exception as exc:
            messages.error(request, f'Could not save quarterly backup: {exc}')
            return redirect(reverse('admin:download_database') + '?auto=0')

        _audit(
            request.user,
            'DatabaseExport',
            (
                f'Quarterly full database ZIP Q{quarter} {year} '
                f'by {request.user}'
            ),
            f'Q{quarter}-{year}-{stamp}',
        )

        messages.success(
            request,
            f'Q{quarter} {year} backup saved. Your ZIP download should start.',
        )
        response = HttpResponse(content, content_type='application/zip')
        response['Content-Disposition'] = (
            f'attachment; filename="pms-database-Q{quarter}-{year}-{stamp}.zip"'
        )
        return response


class DownloadDatabaseHistoryView(View):
    """List all saved database downloads."""

    template_name = 'admin/core/download_database_history.html'

    @method_decorator(staff_member_required)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can view database download history.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from core.models import DatabaseDownload, QuarterlyDatabaseBackup

        downloads = DatabaseDownload.objects.select_related('created_by')
        quarterly = QuarterlyDatabaseBackup.objects.select_related(
            'download', 'created_by'
        )
        context = {
            **admin.site.each_context(request),
            'title': 'Database download history',
            'downloads': downloads,
            'quarterly_backups': quarterly,
            'export_url': reverse('admin:download_database'),
            'json_url': reverse('admin:download_database_json'),
            'zip_url': reverse('admin:download_database_zip'),
            'opts': None,
            'has_permission': True,
        }
        return render(request, self.template_name, context)


class DownloadSavedFileView(View):
    """Re-download a previously saved export from history."""

    @method_decorator(staff_member_required)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can download saved database exports.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        from core.models import DatabaseDownload

        record = get_object_or_404(DatabaseDownload, pk=pk)
        if not record.file:
            raise Http404('File missing.')
        try:
            handle = record.file.open('rb')
        except FileNotFoundError as exc:
            raise Http404('File not found on disk.') from exc

        content_type = (
            'application/zip'
            if record.export_format == 'zip'
            else 'application/json'
        )
        response = FileResponse(handle, content_type=content_type)
        response['Content-Disposition'] = (
            f'attachment; filename="{record.filename}"'
        )
        return response


class ExportDatabaseFileView(View):
    """Stream JSON or ZIP dump of all database app data and save to history."""

    export_format = 'json'  # or 'zip'

    @method_decorator(staff_member_required)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can download the full database.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        year, quarter = _parse_quarter_params(request)
        try:
            payload = build_database_dump_json()
            json.loads(payload)
        except Exception as exc:
            messages.error(request, f'Database export failed: {exc}')
            return redirect(reverse('admin:download_database') + '?auto=0')

        try:
            _record, content = save_database_download(
                request.user,
                self.export_format,
                stamp,
                payload,
                year=year,
                quarter=quarter,
            )
        except Exception as exc:
            messages.warning(
                request,
                f'Download will continue, but history save failed: {exc}',
            )
            if self.export_format == 'zip':
                content = build_database_dump_zip(payload, stamp)
            else:
                content = payload.encode('utf-8')

        label = f' Q{quarter} {year}' if year and quarter else ''
        _audit(
            request.user,
            'DatabaseExport',
            (
                f'Full database download ({self.export_format}){label} '
                f'by {request.user}'
            ),
            stamp,
        )

        qtag = f'-Q{quarter}-{year}' if year and quarter else ''
        if self.export_format == 'zip':
            response = HttpResponse(content, content_type='application/zip')
            response['Content-Disposition'] = (
                f'attachment; filename="pms-database{qtag}-{stamp}.zip"'
            )
            return response

        response = HttpResponse(content, content_type='application/json')
        response['Content-Disposition'] = (
            f'attachment; filename="pms-database{qtag}-{stamp}.json"'
        )
        return response


class ImportDatabaseView(View):
    """Accept a JSON/ZIP fixture upload and load it into the database."""

    @method_decorator(staff_member_required)
    @method_decorator(csrf_protect)
    def dispatch(self, request, *args, **kwargs):
        if not _is_superuser(request.user):
            return HttpResponseForbidden(
                'Only superusers can import the full database.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return redirect('admin:download_database')

    def _wants_json(self, request) -> bool:
        accept = (request.headers.get('Accept') or '').lower()
        return (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in accept
            or request.POST.get('ajax') == '1'
        )

    def _json(self, ok: bool, message: str, **extra):
        from django.http import JsonResponse
        payload = {'ok': ok, 'message': message, **extra}
        return JsonResponse(payload, status=200 if ok else 400)

    def post(self, request):
        wants_json = self._wants_json(request)
        uploaded = request.FILES.get('fixture_file')

        if not uploaded:
            msg = 'Choose a .json or .zip file to import.'
            if wants_json:
                return self._json(False, msg, stage='upload')
            messages.error(request, msg)
            return redirect('admin:download_database')

        try:
            payload, source_label = extract_fixture_bytes(uploaded)
            objects, object_count = validate_fixture(payload)
        except ValueError as exc:
            if wants_json:
                return self._json(False, str(exc), stage='validate')
            messages.error(request, str(exc))
            return redirect('admin:download_database')
        except Exception as exc:
            msg = f'Could not read upload: {exc}'
            if wants_json:
                return self._json(False, msg, stage='validate')
            messages.error(request, msg)
            return redirect('admin:download_database')

        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        try:
            with transaction.atomic():
                # Always merge: add new rows and update matching keys.
                # Never wipe existing data.
                prepared, payload = prepare_fixture_for_load(objects)
                object_count = len(prepared)
                result_msg = load_fixture_bytes(payload)
        except Exception as exc:
            msg = f'Import failed — no changes were saved. Error: {exc}'
            if wants_json:
                return self._json(False, msg, stage='load')
            messages.error(request, msg)
            return redirect('admin:download_database')

        success_msg = (
            f'Import complete (added/updated; existing users kept): '
            f'{object_count} object(s) from {source_label}. {result_msg}'
        )
        _audit(
            request.user,
            'DatabaseImport',
            (
                f'Merged {object_count} objects from {source_label} '
                f'(users preserved) by {request.user}'
            ),
            stamp,
        )
        if wants_json:
            return self._json(
                True,
                success_msg,
                stage='done',
                object_count=object_count,
                source=source_label,
            )
        messages.success(request, success_msg)
        return redirect(reverse('admin:download_database') + '?auto=0')


def get_download_admin_urls():
    """Extra admin URLs for database download and import."""
    return [
        path(
            'download-database/',
            admin.site.admin_view(DownloadDatabaseView.as_view()),
            name='download_database',
        ),
        path(
            'download-database/schedule/',
            admin.site.admin_view(AutoDownloadScheduleView.as_view()),
            name='download_database_schedule',
        ),
        path(
            'download-database/quarter/',
            admin.site.admin_view(QuarterlyDatabaseBackupView.as_view()),
            name='download_database_quarter',
        ),
        path(
            'download-database/history/',
            admin.site.admin_view(DownloadDatabaseHistoryView.as_view()),
            name='download_database_history',
        ),
        path(
            'download-database/history/<int:pk>/file/',
            admin.site.admin_view(DownloadSavedFileView.as_view()),
            name='download_database_saved_file',
        ),
        path(
            'download-database/json/',
            admin.site.admin_view(
                ExportDatabaseFileView.as_view(export_format='json')
            ),
            name='download_database_json',
        ),
        path(
            'download-database/zip/',
            admin.site.admin_view(
                ExportDatabaseFileView.as_view(export_format='zip')
            ),
            name='download_database_zip',
        ),
        path(
            'download-database/import/',
            admin.site.admin_view(ImportDatabaseView.as_view()),
            name='import_database',
        ),
    ]
