"""Printer protocol adapters used by the local Markify Print Agent.

The web application stores a stable driver id. The agent owns the actual
protocol implementation so adding a printer family does not affect the print
queue or HTTP API.
"""
from __future__ import annotations

import os
import socket
import sys
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class PrinterAdapter:
    driver: str
    label: str
    description: str
    protocol: str
    requires_host: bool = False
    requires_queue: bool = False


def fmt_iso(iso: str, tz_name: str) -> str:
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(ZoneInfo(tz_name)).strftime('%d.%m.%Y %H:%M')


def zpl_escape(value: str) -> str:
    return str(value).replace('^', ' ').replace('~', ' ').replace('\\', '/')


def tspl_escape(value: str) -> str:
    return str(value).replace('"', "'").replace('\r', ' ').replace('\n', ' ')


def zpl(payload: dict) -> bytes:
    from .label_render import label_image, bitmap
    chunks = []
    for label in payload['labels']:
        image = label_image(payload, label)
        stride, data = bitmap(image, black_is_one=True)
        chunks.append((f'^XA^CI28^PW{image.width}^LL{image.height}^FO0,0'
                       f'^GFA,{len(data)},{len(data)},{stride},{data.hex().upper()}^FS^XZ').encode('ascii'))
    return b'\n'.join(chunks)


def tspl(payload: dict) -> bytes:
    from .label_render import label_image, bitmap
    printer = payload['printer']
    chunks = [('SIZE %d mm,%d mm\r\nGAP 2 mm,0 mm\r\nDIRECTION 1\r\n' %
               (printer['width_mm'], printer['height_mm'])).encode('ascii')]
    for label in payload['labels']:
        image = label_image(payload, label)
        stride, data = bitmap(image)  # TSPL overwrite bitmap: zero = black.
        chunks.extend([f'CLS\r\nBITMAP 0,0,{stride},{image.height},0,'.encode('ascii'),
                       data, b'\r\nPRINT 1,1\r\n'])
    return b''.join(chunks)


def raw_text(payload: dict) -> bytes:
    chunks = []
    for x in payload['labels']:
        chunks += [
            payload['product']['name'],
            f'Изготовлено: {fmt_iso(x["created_at"], payload.get("timezone", "Europe/Moscow"))}',
            f'Годен до: {fmt_iso(x["expires_at"], payload.get("timezone", "Europe/Moscow"))}',
            x.get('storage') or '', '\n'
        ]
    return '\n'.join(chunks).encode('utf-8')


def escpos(payload: dict) -> bytes:
    from .label_render import label_image, bitmap
    chunks = [b'\x1b@']
    for label in payload['labels']:
        image = label_image(payload, label)
        stride, data = bitmap(image, black_is_one=True)
        chunks.extend([b'\x1dv0\x00' + stride.to_bytes(2, 'little') + image.height.to_bytes(2, 'little'),
                       data, b'\n\x1dV\x00'])
    return b''.join(chunks)


def send_tcp(host: str, port: int, data: bytes) -> None:
    with socket.create_connection((host, port), timeout=7) as sock:
        sock.sendall(data)


def send_cups(payload: dict) -> None:
    queue = payload['printer'].get('queue_name') or ''
    if not queue:
        raise RuntimeError('Для системного принтера не задана очередь CUPS')
    fd, path = tempfile.mkstemp(prefix='markify-', suffix='.ps')
    os.close(fd)
    try:
        with open(path, 'wb') as f:
            from .label_render import postscript
            f.write(postscript(payload))
        subprocess.run(['lp', '-d', queue, '-o', 'job-sheets=none',
                        '-o', 'media=Custom.%dx%dmm' % (payload['printer']['width_mm'], payload['printer']['height_mm']),
                        path], check=True, timeout=20, capture_output=True)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def send_windows(payload: dict) -> None:
    """Render through the installed Windows driver; paper size is set in Windows."""
    if sys.platform != 'win32':
        raise RuntimeError('Этот способ печати требует агента на Windows')
    import win32ui
    from PIL import ImageWin
    from .label_render import label_image
    queue = payload['printer'].get('queue_name', '').strip()
    if not queue:
        raise RuntimeError('Укажите точное имя принтера Windows')
    # Validate every label before submitting any pages.
    images = [label_image(payload, label).convert('RGB') for label in payload['labels']]
    dc = win32ui.CreateDC()
    started = False
    try:
        dc.CreatePrinterDC(queue)
        dpi_x, dpi_y = dc.GetDeviceCaps(88), dc.GetDeviceCaps(90)
        width, height = dc.GetDeviceCaps(110), dc.GetDeviceCaps(111)
        if dpi_x <= 0 or dpi_y <= 0:
            raise RuntimeError('Драйвер Windows не сообщил разрешение принтера')
        target_w = round(payload['printer']['width_mm'] * dpi_x / 25.4)
        target_h = round(payload['printer']['height_mm'] * dpi_y / 25.4)
        if abs(width-target_w) > dpi_x / 25.4 or abs(height-target_h) > dpi_y / 25.4:
            raise RuntimeError('Размер бумаги в настройках Windows не совпадает с этикеткой Markify. Настройте размер и ориентацию в драйвере.')
        offset_x, offset_y = dc.GetDeviceCaps(112), dc.GetDeviceCaps(113)
        dc.StartDoc('Markify labels')
        started = True
        for image in images:
            dc.StartPage()
            ImageWin.Dib(image).draw(dc.GetHandleOutput(),
                (-offset_x, -offset_y, target_w-offset_x, target_h-offset_y))
            dc.EndPage()
        dc.EndDoc()
        started = False
    except Exception:
        if started:
            try:
                dc.AbortDoc()
            except Exception:
                pass
        raise
    finally:
        dc.DeleteDC()


ADAPTERS = {
    'windows': PrinterAdapter('windows', 'Windows / USB', 'Установленный драйвер Windows, USB или системная очередь', 'WINDOWS', requires_queue=True),
    'xprinter': PrinterAdapter('xprinter', 'Xprinter', 'Xprinter / TSPL по TCP 9100', 'TSPL', requires_host=True),
    'tspl': PrinterAdapter('tspl', 'TSPL', 'Любой TSPL-совместимый принтер по TCP 9100', 'TSPL', requires_host=True),
    'zpl': PrinterAdapter('zpl', 'Zebra / ZPL', 'ZPL-совместимый принтер по TCP 9100', 'ZPL', requires_host=True),
    'tsc': PrinterAdapter('tsc', 'TSC', 'TSC / TSPL по TCP 9100', 'TSPL', requires_host=True),
    'raw9100': PrinterAdapter('raw9100', 'Generic RAW', 'RAW TCP 9100', 'RAW', requires_host=True),
    'escpos': PrinterAdapter('escpos', 'ESC/POS', 'ESC/POS по TCP 9100', 'ESC/POS', requires_host=True),
    'godex': PrinterAdapter('godex', 'Godex', 'Godex через установленный системный драйвер/CUPS', 'CUPS', requires_queue=True),
    'atol': PrinterAdapter('atol', 'Atol', 'Atol через системный драйвер/CUPS', 'CUPS', requires_queue=True),
    'cups': PrinterAdapter('cups', 'CUPS', 'Системный драйвер macOS/Linux через CUPS', 'CUPS', requires_queue=True),
}


def render(driver: str, payload: dict) -> bytes | None:
    if driver in {'xprinter', 'tspl', 'tsc'}:
        return tspl(payload)
    if driver == 'zpl':
        return zpl(payload)
    if driver == 'raw9100':
        return raw_text(payload)
    if driver == 'escpos':
        return escpos(payload)
    if driver in {'cups', 'atol', 'godex'}:
        return None
    raise RuntimeError(f'Неподдерживаемый драйвер: {driver}')


def send(driver: str, payload: dict) -> None:
    if driver == 'windows':
        send_windows(payload)
        return
    data = render(driver, payload)
    if data is None:
        send_cups(payload)
        return
    printer = payload['printer']
    host = printer.get('host')
    port = int(printer.get('port') or 9100)
    if not host:
        raise RuntimeError(f'Для драйвера {driver} не указан IP/host принтера')
    send_tcp(host, port, data)
