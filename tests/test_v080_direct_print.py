import os
import socket
import threading

os.environ.setdefault("MARKIFY_AGENT_TOKEN", "test-token")

from agent.agent import tspl, send_tcp


def test_xprinter_tspl_payload_is_directly_sendable_over_tcp():
    received = []
    ready = threading.Event()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()

    def run():
        ready.set()
        conn, _ = server.accept()
        with conn:
            chunks = []
            while True:
                chunk = conn.recv(65535)
                if not chunk: break
                chunks.append(chunk)
            received.append(b''.join(chunks))

    thread = threading.Thread(target=run, daemon=True)
    thread.start(); ready.wait(1)
    payload = {
        "printer": {"width_mm": 58, "height_mm": 40},
        "product": {"name": "Test Xprinter", "storage_condition": "0…+4 °C"},
        "timezone": "Europe/Moscow",
        "labels": [{"created_at": "2026-10-02T09:00:00+00:00", "expires_at": "2026-10-02T11:00:00+00:00", "storage": "0…+4 °C"}],
    }
    data = tspl(payload)
    send_tcp(host, port, data)
    thread.join(2); server.close()
    assert received and received[0].startswith(b"SIZE 58 mm,40 mm")
    assert b"PRINT 1,1" in received[0]


def test_xprinter_driver_is_explicitly_supported():
    from app.schemas import PrinterCreate
    p = PrinterCreate(name="Xprinter", driver="xprinter", host="192.168.1.50")
    assert p.driver == "xprinter"
