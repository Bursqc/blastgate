"""
OTA update client for Blastgate hub.

Workflow:
1. fetch_current_version(hub_ip) — GET http://hub/version
2. fetch_remote_manifest(url)    — GET manifest.json from release server
3. is_update_available(...)      — semver compare
4. download_firmware(url, ...)   — stream binary to local temp, verify SHA256
5. upload_to_hub(...)            — POST /ota with X-OTA-Token header
6. wait_for_reboot(hub_ip)       — poll /version until new version appears

UI plumbing should wrap step-by-step calls with progress callbacks.
Hub firmware side: see firmware/hub-wt32/src/main.cpp (/version, /ota endpoints).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Standard HTTP timeouts (seconds). Hub is on LAN/AP, manifest is on the internet.
_HUB_TIMEOUT = 5.0
_MANIFEST_TIMEOUT = 10.0
_DOWNLOAD_TIMEOUT = 60.0
_UPLOAD_TIMEOUT = 90.0


@dataclass
class HubVersion:
    """Parsed response from GET /version."""
    version: str
    build: str
    uptime: int
    free_heap: int
    proto_ver: str
    chip_model: str = ""
    ota_partition: str = ""

    @classmethod
    def from_json(cls, data: dict) -> "HubVersion":
        return cls(
            version=str(data.get("version", "0.0.0")),
            build=str(data.get("build", "")),
            uptime=int(data.get("uptime", 0)),
            free_heap=int(data.get("freeHeap", 0)),
            proto_ver=str(data.get("protoVer", "?")),
            chip_model=str(data.get("chipModel", "")),
            ota_partition=str(data.get("otaPartition", "")),
        )


@dataclass
class OtaManifest:
    """Parsed release manifest fetched from update server."""
    version: str
    url: str
    size: int
    sha256: str
    min_prev_version: str = ""
    changelog: str = ""

    @classmethod
    def from_json(cls, data: dict) -> "OtaManifest":
        return cls(
            version=str(data["version"]),
            url=str(data["url"]),
            size=int(data.get("size", 0)),
            sha256=str(data.get("sha256", "")).lower(),
            min_prev_version=str(data.get("minPrevVersion", "")),
            changelog=str(data.get("changelog", "")),
        )


def _semver_tuple(v: str) -> tuple:
    """Parse '1.2.3' or '1.2.3-rc1' → (1,2,3). Suffixes are stripped for comparison."""
    core = v.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def is_newer(remote: str, current: str) -> bool:
    """True if remote semver > current semver."""
    return _semver_tuple(remote) > _semver_tuple(current)


def fetch_current_version(hub_ip: str, timeout: float = _HUB_TIMEOUT) -> HubVersion:
    """GET http://<hub>/version → HubVersion."""
    url = f"http://{hub_ip}/version"
    logger.info("OTA: fetching hub version from %s", url)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return HubVersion.from_json(data)


def fetch_remote_manifest(manifest_url: str, timeout: float = _MANIFEST_TIMEOUT) -> OtaManifest:
    """GET manifest.json from update server → OtaManifest."""
    logger.info("OTA: fetching manifest from %s", manifest_url)
    req = urllib.request.Request(manifest_url, headers={"User-Agent": "BlastgateDesktop/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return OtaManifest.from_json(data)


def download_firmware(
    manifest: OtaManifest,
    dest_path: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = _DOWNLOAD_TIMEOUT,
) -> Path:
    """
    Download firmware.bin from manifest.url to dest_path.
    Verifies SHA256 if manifest.sha256 is set. Raises ValueError on mismatch.
    progress_cb(downloaded_bytes, total_bytes) called as data flows.
    """
    logger.info("OTA: downloading %s → %s", manifest.url, dest_path)
    sha = hashlib.sha256()
    written = 0
    total = manifest.size or 0
    req = urllib.request.Request(manifest.url, headers={"User-Agent": "BlastgateDesktop/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if total == 0:
            try:
                total = int(r.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                total = 0
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            while True:
                chunk = r.read(16 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                written += len(chunk)
                if progress_cb:
                    progress_cb(written, total)

    if manifest.sha256:
        got = sha.hexdigest()
        if got != manifest.sha256:
            dest_path.unlink(missing_ok=True)
            raise ValueError(f"SHA256 mismatch: got {got}, expected {manifest.sha256}")
    logger.info("OTA: download complete (%d bytes)", written)
    return dest_path


def upload_to_hub(
    hub_ip: str,
    firmware_path: Path,
    token: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = _UPLOAD_TIMEOUT,
) -> dict:
    """
    POST firmware.bin to http://<hub>/ota as multipart/form-data.
    Returns parsed JSON response from hub. Hub reboots on success.
    """
    url = f"http://{hub_ip}/ota"
    size = firmware_path.stat().st_size
    logger.info("OTA: uploading %s (%d bytes) → %s", firmware_path, size, url)

    boundary = f"----BlastgateOTA{int(time.time())}"
    pre = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="firmware"; filename="firmware.bin"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode("utf-8")
    content_length = len(pre) + size + len(post)

    # Stream body to avoid loading entire firmware into RAM
    with open(firmware_path, "rb") as f:
        body = pre + f.read() + post

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(content_length),
            "X-OTA-Token": token,
            "User-Agent": "BlastgateDesktop/1.0",
        },
    )
    if progress_cb:
        progress_cb(size, size)  # urllib doesn't expose upload progress; signal completion only

    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp_data = r.read().decode("utf-8")
    try:
        return json.loads(resp_data)
    except json.JSONDecodeError:
        return {"ok": False, "error": "non-json response", "raw": resp_data}


def wait_for_reboot(
    hub_ip: str,
    expected_version: str,
    timeout_s: float = 60.0,
    poll_interval_s: float = 2.0,
) -> bool:
    """
    Poll /version until hub returns expected_version or timeout.
    Hub takes ~5-10s to reboot and reconnect to network.
    Returns True if expected_version was observed, False on timeout.
    """
    deadline = time.time() + timeout_s
    last_seen: Optional[str] = None
    while time.time() < deadline:
        try:
            v = fetch_current_version(hub_ip, timeout=2.0)
            last_seen = v.version
            if v.version == expected_version:
                logger.info("OTA: hub back online with version %s", v.version)
                return True
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass  # hub still rebooting
        time.sleep(poll_interval_s)
    logger.warning("OTA: timeout waiting for hub reboot (last seen: %s)", last_seen)
    return False


def check_and_get_update(
    hub_ip: str,
    manifest_url: str,
) -> tuple[HubVersion, Optional[OtaManifest]]:
    """
    One-shot helper: fetch hub /version + remote manifest, return both.
    Manifest is None if it can't be reached (no internet, server down).
    Caller decides whether to prompt user based on is_newer(manifest.version, hub.version).
    """
    hub_ver = fetch_current_version(hub_ip)
    manifest: Optional[OtaManifest] = None
    try:
        manifest = fetch_remote_manifest(manifest_url)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as e:
        logger.warning("OTA: manifest unreachable: %s", e)
    return hub_ver, manifest
