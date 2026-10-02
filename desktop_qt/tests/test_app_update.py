"""Self-update of the desktop app: manifest parsing, download + verification, UI strip states."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from blastgate.network.app_update import (DesktopRelease, download_setup, fetch_releases, setup_path,
                                          update_available)
from blastgate.network.ota import OtaManifest
from blastgate.ui.update_bar import app_strip_state, hub_strip_state

SETUP_BYTES = b"MZ" + bytes(range(256)) * 400     # stands in for the installer
SETUP_SHA = hashlib.sha256(SETUP_BYTES).hexdigest()


@pytest.fixture()
def server():
    """Release server on the loopback interface: /manifest.json, /setup.exe, /old.json."""
    files = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = files.get(self.path.split("?", 1)[0])
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *a):  # keep test output clean
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{httpd.server_port}"
    firmware = {"version": "1.5.1", "url": f"{base}/firmware.bin", "size": 10, "sha256": "ab",
                "minPrevVersion": "1.2.0", "changelog": "fw"}
    files["/setup.exe"] = SETUP_BYTES
    files["/old.json"] = json.dumps(firmware).encode()
    files["/manifest.json"] = json.dumps({**firmware, "desktop": {
        "version": "2.3.0", "url": f"{base}/setup.exe", "size": len(SETUP_BYTES), "sha256": SETUP_SHA,
        "changelog": "- novo"}}).encode()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield base
    httpd.shutdown()


def test_manifest_with_desktop_section(server):
    fw, desktop = fetch_releases(f"{server}/manifest.json")
    assert fw.version == "1.5.1" and fw.min_prev_version == "1.2.0"
    assert desktop.version == "2.3.0" and desktop.sha256 == SETUP_SHA and desktop.changelog == "- novo"


def test_manifest_without_desktop_section_is_still_valid(server):
    fw, desktop = fetch_releases(f"{server}/old.json")
    assert fw.version == "1.5.1"
    assert desktop is None


def test_update_available_compares_versions():
    rel = DesktopRelease(version="2.3.0", url="x")
    assert update_available(rel, "2.2.0")
    assert update_available(rel, "2.2.9")
    assert not update_available(rel, "2.3.0")
    assert not update_available(rel, "2.10.0")
    assert not update_available(None, "1.0.0")


def test_download_verifies_and_keeps_only_the_new_installer(server, tmp_path: Path):
    (tmp_path / "Blastgate-2.2.0-Setup.exe").write_bytes(b"old")
    rel = DesktopRelease(version="2.3.0", url=f"{server}/setup.exe", size=len(SETUP_BYTES), sha256=SETUP_SHA)
    seen = []
    path = download_setup(rel, tmp_path, lambda done, total: seen.append((done, total)))

    assert path == setup_path(rel, tmp_path) and path.read_bytes() == SETUP_BYTES
    assert seen[-1] == (len(SETUP_BYTES), len(SETUP_BYTES))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Blastgate-2.3.0-Setup.exe"]

    # already downloaded: returned as is, nothing fetched again
    path.write_bytes(b"kept")
    assert download_setup(rel, tmp_path).read_bytes() == b"kept"


def test_download_with_wrong_checksum_leaves_nothing_behind(server, tmp_path: Path):
    rel = DesktopRelease(version="2.3.0", url=f"{server}/setup.exe", sha256="0" * 64)
    with pytest.raises(ValueError):
        download_setup(rel, tmp_path)
    assert list(tmp_path.iterdir()) == []


def _updater(**kw):
    base = dict(self_update=True, app_update=True, app_hidden=False, setup=None, downloading=False, progress=0,
                release=DesktopRelease(version="2.3.0", url="x"), hub_update=False, hub_hidden=False,
                firmware=OtaManifest(version="1.5.2", url="x", size=0, sha256=""), hub_version="1.5.1")
    return SimpleNamespace(**{**base, **kw})


def test_app_strip_follows_the_download():
    assert app_strip_state(_updater(downloading=True, progress=40)) == (
        True, "Preuzimam novu verziju aplikacije 2.3.0… 40 %", "")
    assert app_strip_state(_updater(setup=Path("x.exe"))) == (
        True, "Nova verzija aplikacije 2.3.0 je spremna.", "Instaliraj i pokreni ponovo")
    assert app_strip_state(_updater())[2] == "Preuzmi"              # download failed: offer a retry


def test_app_strip_hidden_when_it_cannot_or_should_not_show():
    assert app_strip_state(_updater(app_update=False))[0] is False
    assert app_strip_state(_updater(app_hidden=True))[0] is False
    assert app_strip_state(_updater(self_update=False))[0] is False  # run from source


def test_hub_strip():
    assert hub_strip_state(_updater())[0] is False
    assert hub_strip_state(_updater(hub_update=True)) == (
        True, "Novi firmware za hub 1.5.2 (sada 1.5.1).", "Ažuriraj hub")
    assert hub_strip_state(_updater(hub_update=True, hub_hidden=True))[0] is False


# ------------------------------------------------------------------ AppUpdater
@pytest.fixture()
def updater(monkeypatch, tmp_path):
    """AppUpdater of an installed (self-updating) copy, with background work run inline."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    from blastgate.ui import updater as mod

    app = QApplication.instance() or QApplication([])

    class Ctl(QObject):
        status_changed = Signal(dict, str)

        def __init__(self):
            super().__init__()
            self.demo_hub = None
            self.status = {"version": "1.5.1"}
            self.cfg = SimpleNamespace(ota_manifest_url="x", ota_auto_check_s=0)
            self.events = []

        def run_bg(self, work, on_ok=None, on_err=None):
            try:
                result = work()
            except Exception as e:  # noqa: BLE001
                on_err(e)
            else:
                on_ok(result)

        def _ui_after(self, ms, fn):
            fn()

        def add_event(self, tone, text):
            self.events.append(text)

    calls = SimpleNamespace(downloaded=[], launched=[], cleared=[], closed=[])
    monkeypatch.setattr(mod, "APP_VERSION", "2.2.0")
    monkeypatch.setattr(mod, "UPDATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "download_setup",
                        lambda rel, folder, cb=None: calls.downloaded.append(rel.version) or tmp_path / "s.exe")
    monkeypatch.setattr(mod, "launch_setup", lambda p: calls.launched.append(p))
    monkeypatch.setattr(mod, "clear_downloads", lambda folder: calls.cleared.append(folder))
    monkeypatch.setattr(app, "closeAllWindows", lambda: calls.closed.append(True))
    up = mod.AppUpdater(Ctl(), self_update=True)
    return up, calls


def _fw(version="1.5.1"):
    return OtaManifest(version=version, url="x", size=0, sha256="")


def test_newer_release_is_downloaded_then_installed_on_request(updater, tmp_path):
    up, calls = updater
    up._checked((_fw(), DesktopRelease(version="2.3.0", url="x")))
    assert up.app_update and calls.downloaded == ["2.3.0"] and up.setup == tmp_path / "s.exe"
    assert calls.launched == []                      # never installs by itself

    up.install()
    assert calls.launched == [tmp_path / "s.exe"] and calls.closed == [True]


def test_current_release_downloads_nothing_and_clears_old_installers(updater, tmp_path):
    up, calls = updater
    up._checked((_fw(), DesktopRelease(version="2.2.0", url="x")))
    assert not up.app_update and calls.downloaded == [] and calls.cleared == [tmp_path]
    up.install()
    assert calls.launched == []


def test_copy_run_from_source_never_downloads(updater):
    up, calls = updater
    up.self_update = False
    up._checked((_fw(), DesktopRelease(version="2.3.0", url="x")))
    assert up.app_update and calls.downloaded == [] and calls.cleared == []


def test_hub_update_respects_minimum_previous_version(updater):
    up, _ = updater
    up._checked((_fw("1.5.2"), None))
    assert up.hub_update                              # hub reports 1.5.1
    up.firmware = OtaManifest(version="1.6.0", url="x", size=0, sha256="", min_prev_version="1.5.5")
    assert not up.hub_update


def test_failed_check_is_remembered_not_raised(updater, monkeypatch):
    up, _ = updater
    from blastgate.ui import updater as mod

    def boom(url):
        raise OSError("no internet")
    monkeypatch.setattr(mod, "fetch_releases", boom)
    up.check()
    assert up.failed and not up.checking
