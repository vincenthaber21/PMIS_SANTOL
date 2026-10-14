"""Logo image helpers — remove light backgrounds for transparent display."""
from io import BytesIO

from PIL import Image


LOGIN_LOGO_CACHE_PREFIX = 'login_logo:'


def login_logo_cache_key(logo_name):
    return f'{LOGIN_LOGO_CACHE_PREFIX}{logo_name}'


def clear_login_logo_cache(logo_name=None):
    from django.core.cache import cache

    if logo_name:
        cache.delete(login_logo_cache_key(logo_name))


def _color_distance(rgb1, rgb2):
    return sum((a - b) ** 2 for a, b in zip(rgb1, rgb2)) ** 0.5


def _soften_white_edges(pixels, width, height, softness):
    threshold = 255 - softness
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            min_rgb = min(r, g, b)
            if min_rgb >= threshold:
                fade = int(255 * (255 - min_rgb) / max(softness, 1))
                pixels[x, y] = (r, g, b, min(a, max(fade, 0)))


def remove_logo_background(source, tolerance=42, edge_softness=18):
    """
    Remove light/white backgrounds from logo images.

    Flood-fills from the image corners so white boxes and attached shadows
    become transparent while the seal artwork is preserved.
    """
    image = Image.open(source)
    try:
        img = image.convert('RGBA')
    finally:
        image.close()

    width, height = img.size
    pixels = img.load()
    visited = bytearray(width * height)

    def index(x, y):
        return y * width + x

    stack = []
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        ref = pixels[x, y][:3]
        stack.append((x, y, ref))

    while stack:
        x, y, ref = stack.pop()
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        pos = index(x, y)
        if visited[pos]:
            continue

        r, g, b, _alpha = pixels[x, y]
        if min(r, g, b) >= 250 or _color_distance((r, g, b), ref) <= tolerance:
            visited[pos] = 1
            pixels[x, y] = (r, g, b, 0)
            stack.extend([
                (x + 1, y, ref),
                (x - 1, y, ref),
                (x, y + 1, ref),
                (x, y - 1, ref),
            ])

    if edge_softness:
        _soften_white_edges(pixels, width, height, edge_softness)

    return img


def logo_to_png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()
