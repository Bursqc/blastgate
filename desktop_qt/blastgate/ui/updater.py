"""
App-wide update state for the UI: what is released, what is installed, and
the download/installation of a new desktop version.

Checks the release manifest shortly after start and then every
cfg.ota_auto_check_s. A newer desktop version is downloaded in the background;
the UI then offers „Instaliraj" — the installer is never started without the
user, because it closes the app.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from ..constants import APP_VERSION, UPDATE_DIR
from ..network.app_update import (DesktopRelease, can_self_update, clear_downloads, download_setup,
                                  fetch_releases, launch_setup, update_available)
from ..network.ota import OtaManifest, is_newer
from .controller import Controller

logger = logging.getLogger(__name__)


class AppUpdater(QObject):
    changed = Signal()

    def __init__(self, ctl: Controller, self_update: Optional[bool] = None) -> None:
        super().__init__()
        self.ctl = ctl
        # A copy run from source cannot replace itself; it still shows what is released
        self.self_update = can_self_update() if self_update is None else self_update
        self.release: Optional[DesktopRelease] = None
        self.firmware: Optional[OtaManifest] = None
        self.setup: Optional[Path] = None      # downloaded and verified installer
        self.checking = False
        self.downloading = False
        self.progress = 0                      # download, percent
        self.failed = False                    # last check did not reach the server
        self.checked_at: Optional[datetime] = None
        self.app_hidden = False                # „Kasnije" on the overview strips
        self.hub_hidden = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        ctl.status_changed.connect(lambda *_: self.changed.emit())   # hub version may have changed

    def start(self) -> None:
        if self.ctl.demo_hub:
            return
        QTimer.singleShot(4000, self.check)
        if self.ctl.cfg.ota_auto_check_s > 0:
            self._timer.start(self.ctl.cfg.ota_auto_check_s * 1000)

    # ------------------------------------------------------------- state
    @property
    def app_update(self) -> bool:
        return update_available(self.release, APP_VERSION)

    @property
    def hub_version(self) -> str:
        return str(self.ctl.status.get("version") or "") if self.ctl.status else ""

    @property
    def hub_update(self) -> bool:
        fw, cur = self.firmware, self.hub_version
        if not (fw and cur and is_newer(fw.version, cur)):
            return False
        return not fw.min_prev_version or not is_newer(fw.min_prev_version, cur)

    # ------------------------------------------------------------- check
    def check(self) -> None:
        if self.checking:
            return
        self.checking = True
        self.changed.emit()
        self.ctl.run_bg(lambda: fetch_releases(self.ctl.cfg.ota_manifest_url), self._checked, self._check_failed)

    def _checked(self, result) -> None:
        self.firmware, self.release = result
        self.checking = False
        self.failed = False
        self.checked_at = datetime.now()
        self.changed.emit()
        if not self.self_update:
            return
        if self.app_update:
            self._download()
        else:
            clear_downloads(UPDATE_DIR)

    def _check_failed(self, e: Exception) -> None:
        logger.info("Update check failed: %s", e)
        self.checking = False
        self.failed = True
        self.changed.emit()

    # ---------------------------------------------------------- download
    def _download(self) -> None:
        if self.downloading or self.setup or not self.release:
            return
        self.downloading = True
        self.progress = 0
        self.changed.emit()
        release = self.release

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / total) if total else 0
            if pct != self.progress:               # one UI update per percent, not per chunk
                self.progress = pct
                self.ctl._ui_after(0, self.changed.emit)

        self.ctl.run_bg(lambda: download_setup(release, UPDATE_DIR, progress), self._downloaded,
                        self._download_failed)

    def _downloaded(self, path: Path) -> None:
        self.setup = path
        self.downloading = False
        self.ctl.add_event("info", f"Nova verzija aplikacije {self.release.version} je preuzeta")
        self.changed.emit()

    def _download_failed(self, e: Exception) -> None:
        logger.warning("Update download failed: %s", e)
        self.downloading = False
        self.changed.emit()                         # tried again at the next check

    # ----------------------------------------------------------- install
    def install(self) -> None:
        """Start the installer and close the app; the installer starts the new version."""
        if not self.setup:
            return
        try:
            launch_setup(self.setup)
        except OSError as e:
            logger.error("Cannot start the installer: %s", e)
            self.setup = None                       # download it again next time
            self.changed.emit()
            return
        QApplication.instance().closeAllWindows()
