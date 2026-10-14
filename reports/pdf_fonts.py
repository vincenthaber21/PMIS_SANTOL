"""Register a TrueType font that renders the Philippine peso sign (₱) in ReportLab PDFs."""
from pathlib import Path

PESO_FONT_NAME = 'PesoSans'
_registered_name = None

# Bundled first when added; then common OS font paths (Windows / Linux).
_FONT_CANDIDATES = (
    Path(__file__).resolve().parent / 'fonts' / 'DejaVuSans.ttf',
    Path(r'C:/Windows/Fonts/segoeui.ttf'),
    Path(r'C:/Windows/Fonts/arial.ttf'),
    Path(r'C:/Windows/Fonts/calibri.ttf'),
    Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    Path('/usr/share/fonts/TTF/DejaVuSans.ttf'),
    Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'),
)


def ensure_peso_font():
    """Register and return the peso-capable font name, or None if unavailable."""
    global _registered_name
    if _registered_name is not None:
        return _registered_name or None

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in _FONT_CANDIDATES:
        if not path.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(PESO_FONT_NAME, str(path)))
            _registered_name = PESO_FONT_NAME
            return PESO_FONT_NAME
        except Exception:
            continue

    _registered_name = ''
    return None


def peso_table_font_rules(columns, *, first_row=2):
    """TableStyle FONTNAME tuples for peso amount columns."""
    font = ensure_peso_font()
    if not font:
        return []
    return [('FONTNAME', (col, first_row), (col, -1), font) for col in columns]
