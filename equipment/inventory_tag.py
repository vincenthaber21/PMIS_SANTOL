"""COA Circular 80-124 inventory tag helpers."""
import base64
from io import BytesIO

from django.conf import settings

from core.models import SiteSettings


def _lgu_settings():
    site = SiteSettings.get_solo()
    province = (site.lgu_province or '').strip() or getattr(settings, 'LGU_PROVINCE', 'LA UNION')
    municipality = (site.lgu_municipality or '').strip() or getattr(
        settings, 'LGU_MUNICIPALITY', getattr(settings, 'LGU_NAME', 'MUNICIPALITY'),
    )
    return {
        'province': province,
        'municipality': municipality,
        'lgu_code': (site.property_number_lgu_code or '').strip() or getattr(settings, 'LGU_CODE', '1042'),
    }


def _office_location(equipment):
    department_name = equipment.department.name.strip() if equipment.department else ''
    current_location = (equipment.current_location or '').strip()

    if department_name and current_location:
        if department_name.casefold() == current_location.casefold():
            return department_name
        return f'{department_name} / {current_location}'
    return department_name or current_location


def _person_accountable(equipment):
    if equipment.assigned_user:
        return equipment.assigned_user.get_full_name() or equipment.assigned_user.username
    return ''


def _is_serviceable(equipment):
    if equipment.property_status:
        return 'unserviceable' not in equipment.property_status.name.lower()
    if equipment.status in ('Retired', 'Maintenance'):
        return False
    if equipment.condition_score is not None and equipment.condition_score < 30:
        return False
    return True


def build_qr_data_uri(text, *, box_size=8, border=3):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L

    # ERROR_CORRECT_L keeps the QR version (module count) as low as possible so the
    # code stays readable even when printed small with many detail lines encoded.
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_L,
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def _property_custodian_display_name(request=None):
    """Supply officer / property custodian name for inventory tag signature blocks."""
    from core.signatories import default_supply_officer_user, resolve_par_download_supply_officer

    if request and getattr(request, 'user', None) and request.user.is_authenticated:
        officer = resolve_par_download_supply_officer(request.user)
    else:
        officer = default_supply_officer_user()
    if not officer:
        return ''
    return officer.get_full_name() or officer.username


def resolve_inventory_tag_representative_name(site, request=None):
    """COA Representative — site default, then property custodian / supply officer."""
    site_value = (site.inventory_tag_coa_representative or '').strip()
    if site_value:
        return site_value
    return _property_custodian_display_name(request)


def get_inventory_tag_context(equipment, request=None):
    """Build template context for a single COA inventory tag."""
    lgu = _lgu_settings()
    site = SiteSettings.get_solo()
    serviceable = _is_serviceable(equipment)

    logo_url = ''
    if site.logo:
        logo_url = site.logo.url
        if request is not None:
            logo_url = request.build_absolute_uri(logo_url)

    person_accountable = _person_accountable(equipment)
    property_custodian_name = _property_custodian_display_name(request)
    representative_name = resolve_inventory_tag_representative_name(site, request)
    date_counted = site.inventory_tag_date_counted or equipment.last_inspection_date

    qr_payload = equipment.get_qr_payload() if equipment.pk else ''
    qr_code_data = build_qr_data_uri(qr_payload, box_size=8, border=3) if qr_payload else ''
    lgu_code = lgu['lgu_code']
    property_number = (equipment.property_number or '').strip()
    # The code stays on the tag even when property numbers use LGU-{Municipality}.
    show_lgu_code = bool(lgu_code) and not property_number.casefold().startswith(
        lgu_code.casefold(),
    )

    return {
        'equipment': equipment,
        'site_settings': site,
        'logo_url': logo_url,
        'lgu_province': lgu['province'],
        'lgu_municipality': lgu['municipality'],
        'lgu_code': lgu_code,
        'show_lgu_code': show_lgu_code,
        'inventory_number': equipment.property_number,
        'office_location': _office_location(equipment),
        'person_accountable': person_accountable,
        'article_name': equipment.display_name,
        'property_number': equipment.property_number,
        'serial_number': equipment.serial_number or '',
        'is_serviceable': serviceable,
        'quantity': max(int(equipment.quantity or 1), 1),
        'acquisition_cost': equipment.acquisition_cost or equipment.purchase_cost,
        'date_acquired': equipment.purchase_date,
        'date_counted': date_counted,
        'custodian_name': property_custodian_name,
        'representative_name': representative_name,
        'qr_code_data': qr_code_data,
    }
