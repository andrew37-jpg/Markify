import sys
from types import SimpleNamespace
import pytest
from app import printer_adapters as adapters
from app.schemas import PrinterCreate
from tests.test_printer_adapters import payload


class DC:
    def __init__(self, mismatch=False, fail=False):
        self.events = []
        self.mismatch = mismatch
        self.fail = fail
    def CreatePrinterDC(self, queue): self.events.append(('queue', queue))
    def GetDeviceCaps(self, cap):
        return {88:203, 90:203, 110: round((80 if self.mismatch else 58)*203/25.4),
                111:round(40*203/25.4), 112:0, 113:0}[cap]
    def StartDoc(self, name): self.events.append('doc')
    def StartPage(self): self.events.append('page')
    def EndPage(self):
        if self.fail: raise RuntimeError('driver failure')
        self.events.append('endpage')
    def EndDoc(self): self.events.append('enddoc')
    def AbortDoc(self): self.events.append('abort')
    def DeleteDC(self): self.events.append('delete')
    def GetHandleOutput(self): return 1


def setup(monkeypatch, dc):
    from PIL import ImageWin
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setitem(sys.modules, 'win32ui', SimpleNamespace(CreateDC=lambda: dc))
    monkeypatch.setattr(ImageWin, 'Dib', lambda image: SimpleNamespace(draw=lambda *args: dc.events.append('draw')))
    data = payload('windows')
    data['printer']['queue_name'] = 'XP-365B'
    data['labels'] *= 2
    return data


def test_windows_submits_one_page_per_label(monkeypatch):
    dc = DC()
    adapters.send('windows', setup(monkeypatch, dc))
    assert dc.events == [('queue','XP-365B'), 'doc', 'page','draw','endpage', 'page','draw','endpage','enddoc','delete']
    assert PrinterCreate(driver='windows', queue_name='XP-365B').driver == 'windows'


def test_wrong_paper_size_is_rejected_before_spooling(monkeypatch):
    dc = DC(mismatch=True)
    with pytest.raises(RuntimeError, match='Размер бумаги'):
        adapters.send_windows(setup(monkeypatch, dc))
    assert 'doc' not in dc.events
    assert dc.events[-1] == 'delete'


def test_driver_failure_aborts_document_and_releases_dc(monkeypatch):
    dc = DC(fail=True)
    with pytest.raises(RuntimeError, match='driver failure'):
        adapters.send_windows(setup(monkeypatch, dc))
    assert dc.events[-2:] == ['abort', 'delete']
    assert 'enddoc' not in dc.events


def test_agent_download_requires_login_and_excludes_secrets():
    import io
    import re
    import zipfile
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        assert client.get('/api/agent/download', follow_redirects=False).status_code in (303, 401)
        page = client.get('/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        assert client.post('/login', data={'email':'admin@markify.local', 'password':'ChangeMe-Please-2026!', 'csrf_token':token}, follow_redirects=False).status_code == 303
        response = client.get('/api/agent/download')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            assert 'agent/agent.py' in names and 'docs/WINDOWS_PILOT.md' in names
            assert len(names) == 9
            assert 'app/fonts/LICENSE.txt' in names
            assert not any(name.endswith('.db') or name in ('.env','agent/.env') for name in names)
