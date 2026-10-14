"""Bulk QR code export helpers — size, resolution, print and download."""
import io
import re
import zipfile

QR_SIZE_MIN = 0.5
QR_SIZE_MAX = 4.0
QR_SIZE_DEFAULT = 1.0
QR_SPACING_MIN = 0.0
QR_SPACING_MAX = 0.5
QR_SPACING_DEFAULT = 0.08

RESOLUTION_CHOICES = {
    '96': {'dpi': 96, 'box_size': 2, 'border': 1, 'label': '96 DPI (Screen)'},
    '150': {'dpi': 150, 'box_size': 4, 'border': 1, 'label': '150 DPI (Standard Print)'},
    '300': {'dpi': 300, 'box_size': 8, 'border': 2, 'label': '300 DPI (High Quality)'},
    '600': {'dpi': 600, 'box_size': 12, 'border': 2, 'label': '600 DPI (Ultra)'},
}
DEFAULT_RESOLUTION = '150'
LETTER_USABLE_WIDTH_IN = 8.0


def parse_qr_size(raw):
    try:
        size = float(raw)
    except (TypeError, ValueError):
        size = QR_SIZE_DEFAULT
    return max(QR_SIZE_MIN, min(QR_SIZE_MAX, round(size, 2)))


def parse_qr_spacing(raw):
    try:
        spacing = float(raw)
    except (TypeError, ValueError):
        spacing = QR_SPACING_DEFAULT
    return max(QR_SPACING_MIN, min(QR_SPACING_MAX, round(spacing, 2)))


def _columns_for_layout(size_inches, spacing_inches, usable_width=LETTER_USABLE_WIDTH_IN):
    pitch = size_inches + spacing_inches
    if pitch <= 0:
        return 1
    return max(1, int((usable_width + spacing_inches) // pitch))


def parse_show_name(raw):
    if raw is None:
        return True
    return str(raw).lower() not in ('0', 'false', 'no', 'off')


def parse_qr_export_options(params):
    size_inches = parse_qr_size(params.get('qr_size', QR_SIZE_DEFAULT))
    resolution_key = str(params.get('qr_resolution', DEFAULT_RESOLUTION)).strip()
    if resolution_key not in RESOLUTION_CHOICES:
        resolution_key = DEFAULT_RESOLUTION
    resolution = RESOLUTION_CHOICES[resolution_key]
    show_name = parse_show_name(params.get('show_name'))
    spacing_inches = parse_qr_spacing(params.get('qr_spacing', QR_SPACING_DEFAULT))
    columns = _columns_for_layout(size_inches, spacing_inches)
    name_font_pt = max(4.0, min(9.0, round(size_inches * 5.5, 1)))
    return {
        'size_inches': size_inches,
        'spacing_inches': spacing_inches,
        'resolution_key': resolution_key,
        'dpi': resolution['dpi'],
        'box_size': resolution['box_size'],
        'border': resolution['border'],
        'resolution_label': resolution['label'],
        'show_name': show_name,
        'columns': columns,
        'name_font_pt': name_font_pt,
    }


def _build_qr_image(text, *, box_size, border):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L
    from PIL import Image

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_L,
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    return qr.make_image(fill_color='black', back_color='white').convert('RGB')


def _resize_qr_image(img, target_px):
    from PIL import Image

    target_px = max(64, int(target_px))
    if img.size[0] == target_px:
        return img
    return img.resize((target_px, target_px), Image.Resampling.LANCZOS)


def build_qr_png_bytes(text, *, box_size, border, target_px):
    img = _build_qr_image(text, box_size=box_size, border=border)
    img = _resize_qr_image(img, target_px)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


def build_qr_data_uri_for_export(text, options, *, for_print=False):
    if for_print:
        target_px = min(480, int(options['size_inches'] * min(options['dpi'], 300)))
    else:
        target_px = int(options['size_inches'] * options['dpi'])
    png_bytes = build_qr_png_bytes(
        text,
        box_size=options['box_size'],
        border=options['border'],
        target_px=target_px,
    )
    import base64
    encoded = base64.b64encode(png_bytes).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def build_labeled_qr_png_bytes(text, name, *, options):
    from PIL import Image, ImageDraw, ImageFont

    qr_px = max(64, int(options['size_inches'] * options['dpi']))
    qr_img = _resize_qr_image(
        _build_qr_image(text, box_size=options['box_size'], border=options['border']),
        qr_px,
    )

    if not options['show_name'] or not (name or '').strip():
        buffer = io.BytesIO()
        qr_img.save(buffer, format='PNG')
        return buffer.getvalue()

    label = (name or '').strip()
    font_size = max(10, int(qr_px * 0.09))
    try:
        font = ImageFont.truetype('arial.ttf', font_size)
    except OSError:
        font = ImageFont.load_default()

    draw_probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    bbox = draw_probe.multiline_textbbox((0, 0), label, font=font, spacing=2)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    label_width = max(qr_px, text_width + 8)
    label_height = text_height + 8
    canvas = Image.new('RGB', (label_width, qr_px + label_height), 'white')
    canvas.paste(qr_img, ((label_width - qr_px) // 2, 0))

    draw = ImageDraw.Draw(canvas)
    draw.multiline_text(
        ((label_width - text_width) / 2, qr_px + 4),
        label,
        fill='black',
        font=font,
        spacing=2,
        align='center',
    )

    buffer = io.BytesIO()
    canvas.save(buffer, format='PNG')
    return buffer.getvalue()


def safe_qr_filename(property_number, name):
    base = f'{property_number}_{name or "equipment"}'
    base = re.sub(r'[^\w\-.]+', '_', base).strip('._')
    return (base[:120] or 'qr_code') + '.png'


def build_qr_items(queryset, options, *, for_print=False):
    items = []
    for equipment in queryset:
        payload = equipment.get_qr_payload()
        if not payload:
            continue
        items.append({
            'property_number': equipment.property_number,
            'name': equipment.display_name,
            'payload': payload,
            'qr_code_data': build_qr_data_uri_for_export(payload, options, for_print=for_print),
        })
    return items


def build_qr_codes_zip(qr_items, options):
    buffer = io.BytesIO()
    used_names = set()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in qr_items:
            filename = safe_qr_filename(item['property_number'], item['name'])
            stem, ext = filename.rsplit('.', 1)
            counter = 2
            while filename in used_names:
                filename = f'{stem}_{counter}.{ext}'
                counter += 1
            used_names.add(filename)
            png_bytes = build_labeled_qr_png_bytes(
                item['payload'],
                item['name'],
                options=options,
            )
            archive.writestr(filename, png_bytes)
    buffer.seek(0)
    return buffer
