from app.printer_adapters import ADAPTERS, escpos, render, tspl, zpl


def payload(driver='xprinter'):
    return {
        'printer': {'driver': driver, 'width_mm': 58, 'height_mm': 40, 'host': '127.0.0.1', 'port': 9100, 'queue_name': ''},
        'product': {'name': 'Тест', 'storage_condition': '0…+4 °C'},
        'timezone': 'Europe/Moscow',
        'labels': [{'created_at': '2026-10-02T09:00:00+00:00', 'expires_at': '2026-10-02T11:00:00+00:00', 'storage': '0…+4 °C'}],
    }


def test_supported_adapter_catalog_contains_major_families():
    assert {'xprinter', 'zpl', 'tsc', 'godex', 'atol', 'escpos', 'cups', 'raw9100'} <= set(ADAPTERS)


def test_tsc_and_xprinter_share_tspl_renderer():
    assert render('xprinter', payload()) == render('tsc', payload('tsc'))
    assert b'PRINT 1,1' in tspl(payload())


def test_zpl_renderer():
    assert zpl(payload('zpl')).startswith(b'^XA')
    assert b'^CI28' in zpl(payload('zpl'))


def test_escpos_renderer():
    data = escpos(payload('escpos'))
    assert data.startswith(b'\x1b@')
    assert b'\x1dV\x00' in data


def test_cups_and_atol_are_system_driver_adapters():
    assert ADAPTERS['cups'].requires_queue
    assert ADAPTERS['atol'].requires_queue
