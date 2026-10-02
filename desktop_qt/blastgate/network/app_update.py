"""
Self-update of the desktop app.

The release manifest (the same one the hub OTA uses) may carry a "desktop"
section: {"version", "url", "size", "sha256", "changelog"} pointing at the
Windows installer. The app downloads it in the background, verifies it, and —
when the user agrees — starts it silently and exits; the installer replaces
the files and starts the new version.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from .ota import OtaManifest, is_newer

logger = logging.getLogger(__name__)

_MANIFEST_TIMEOUT = 10.0
_DOWNLOAD_TIMEOUT = 60.0
_UA = "BlastgateDesktop"


@dataclass
class DesktopRelease:
    version: str
    url: str
    size: int = 0
    sha256: str = ""
    changelog: str = ""

    @classmethod
    def from_json(cls, data: dict) -> "DesktopRelease":
        return cls(
            version=str(data["version"]),
            url=str(data["url"]),
            size=int(data.get("size", 0)),
            sha256=str(data.get("sha256", "")).lower(),
            changelog=str(data.get("changelog", "")),
        )


def can_self_update() -> bool:
    """Only the installed (frozen) Windows build can replace itself."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def fetch_releases(manifest_url: str,
                   timeout: float = _MANIFEST_TIMEOUT) -> Tuple[OtaManifest, Optional[DesktopRelease]]:
    """Hub firmware + (when the manifest has a "desktop" section) the desktop release."""
    # GitHub's raw CDN caches for 5 minutes; the query string gets a fresh copy
    sep = "&" if "?" in manifest_url else "?"
    req = urllib.request.Request(f"{manifest_url}{sep}t={int(time.time())}",
                                 headers={"User-Agent": _UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    desktop = data.get("desktop")
    return OtaManifest.from_json(data), DesktopRelease.from_json(desktop) if isinstance(desktop, dict) else None


def update_available(release: Optional[DesktopRelease], current_version: str) -> bool:
    return release is not None and is_newer(release.version, current_version)


def setup_path(release: DesktopRelease, folder: Path) -> Path:
    return folder / f"Blastgate-{release.version}-Setup.exe"


def download_setup(release: DesktopRelease, folder: Path,
                   progress_cb: Optional[Callable[[int, int], None]] = None,
                   timeout: float = _DOWNLOAD_TIMEOUT) -> Path:
    """
    Download the installer into [folder] and verify its SHA256.
    Written as *.part and renamed when complete, so a file with the final
    name is always whole. Returns at once when it is already there.
    """
    dest = setup_path(release, folder)
    if dest.exists():
        return dest
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("Blastgate-*-Setup.exe"):   # installers of earlier versions
        old.unlink(missing_ok=True)
    part = folder / "download.part"

    sha = hashlib.sha256()
    written = 0
    req = urllib.request.Request(release.url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = release.size or int(r.headers.get("Content-Length", "0") or 0)
        with open(part, "wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                written += len(chunk)
                if progress_cb:
                    progress_cb(written, total)

    if release.sha256 and sha.hexdigest() != release.sha256:
        part.unlink(missing_ok=True)
        raise ValueError("preuzeta datoteka je oštećena (SHA256 se ne slaže)")
    os.replace(part, dest)
    logger.info("Update: downloaded %s (%d bytes)", dest.name, written)
    return dest


def clear_downloads(folder: Path) -> None:
    """Drop installers left from an update that is already installed."""
    for p in list(folder.glob("Blastgate-*-Setup.exe")) + list(folder.glob("*.part")):
        try:
            p.unlink()
        except OSError as e:
            logger.debug("Update: cannot remove %s: %s", p, e)


def launch_setup(setup: Path) -> None:
    """
    Start the installer silently, detached from this process. The caller must
    quit right after: the installer replaces the app files and starts the new
    version (see packaging/setup.iss, [Run] ... Check: WizardSilent).
    """
    logger.info("Update: starting %s", setup)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
