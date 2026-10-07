"""One raster layout for native protocols and system printing; bundled Cyrillic font."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = Path(__file__).with_name('fonts')


def fmt_iso(value, tz):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo('UTC'))
    return dt.astimezone(ZoneInfo(tz)).strftime('%d.%m.%Y %H:%M')


def wrap(text, font, width):
    lines, line = [], ''
    # Character wrapping also handles names with no whitespace without clipping.
    for char in ' '.join(str(text).split()):
        candidate = line + char
        if font.getlength(candidate) > width and line:
            lines.append(line.rstrip()); line = char.lstrip()
        else:
            line = candidate
    if line:
        lines.append(line.rstrip())
    return lines


def label_image(payload, label):
    printer = payload['printer']; dpi = int(printer.get('dpi', 203))
    width = round(printer['width_mm'] * dpi / 25.4)
    height = round(printer['height_mm'] * dpi / 25.4)
    margin = round(2 * dpi / 25.4)
    tz = payload.get('timezone', 'Europe/Moscow')
    fields = [(label.get('name') or payload['product']['name'], True),
              ('Изготовлено: ' + fmt_iso(label['created_at'], tz), False),
              ('Годен до: ' + fmt_iso(label['expires_at'], tz), True)]
    for key, title in [('storage', 'Хранение: '), ('department', 'Цех: '), ('operator', 'Оператор: ')]:
        if label.get(key): fields.append((title + label[key], False))
    # Never silently truncate a product/date. Refuse an unreadably small layout.
    for points in (9, 8, 7, 6):
        size = round(points * dpi / 72)
        fonts = {bold: ImageFont.truetype(str(FONT_DIR / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')), size) for bold in (False, True)}
        lines = [(text, fonts[bold]) for field, bold in fields for text in wrap(field, fonts[bold], width - margin*2)]
        heights = [sum(font.getmetrics()) + 2 for _, font in lines]
        if sum(heights) <= height - margin*2:
            image = Image.new('L', (width, height), 255); draw = ImageDraw.Draw(image)
            y = margin
            for (line, font), line_height in zip(lines, heights):
                draw.text((margin, y), line, fill=0, font=font, anchor='lt')
                y += line_height
            return image.point(lambda p: 255 if p >= 160 else 0, '1')
    raise ValueError('Текст не помещается на этикетке. Увеличьте размер этикетки или сократите название/условия.')


def bitmap(image, black_is_one=False):
    # Printer widths are expressed in full bytes. Pad right with white.
    padded = Image.new('1', (((image.width+7)//8)*8, image.height), 1)
    padded.paste(image, (0, 0))
    if black_is_one:
        padded = ImageOps.invert(padded.convert('L')).convert('1')
    return padded.width // 8, padded.tobytes()


def postscript(payload):
    """A multi-page print document sent to CUPS, never a user Save/PDF dialog."""
    width = payload['printer']['width_mm'] * 72 / 25.4
    height = payload['printer']['height_mm'] * 72 / 25.4
    parts = ['%!PS-Adobe-3.0', f'%%Pages: {len(payload["labels"])}',
             f'<< /PageSize [{width:.4f} {height:.4f}] >> setpagedevice']
    for number, label in enumerate(payload['labels'], 1):
        image = label_image(payload, label); stride, data = bitmap(image)
        # Pad canvas width by <1 mm; scale padded image to same dot pitch.
        padded_width = stride * 8
        physical_width = width * padded_width / image.width
        parts.extend([f'%%Page: {number} {number}', 'gsave', f'{physical_width:.4f} {height:.4f} scale',
                      f'{padded_width} {image.height} 1 [{padded_width} 0 0 -{image.height} 0 {image.height}]',
                      'currentfile /ASCIIHexDecode filter image', data.hex() + '>', 'grestore', 'showpage'])
    parts.append('%%EOF')
    return '\n'.join(parts).encode('ascii')
