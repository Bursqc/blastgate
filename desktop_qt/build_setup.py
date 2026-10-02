"""
Build the Windows installer of the desktop app: PyInstaller (one folder) -> Inno Setup.

    .venv\\Scripts\\python build_setup.py              # dist\\installer\\Blastgate-<version>-Setup.exe
    .venv\\Scripts\\python build_setup.py --version 2.1.9   # test build that calls itself 2.1.9

The packaged app is started once (demo hub, off-screen) before the installer is
made, so a build that cannot start never becomes a Setup.exe.
An installer that already exists is not overwritten: a delivered file keeps its
content. Bump the version, or pass --force for a build nobody has received.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PACKAGING = ROOT / "packaging"
VERSION_OVERRIDE = ROOT / "blastgate" / "_build_version.py"
ISCC_PLACES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
]


def run(cmd: list, **kw) -> None:
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def freeze() -> Path:
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--noupx",
         "--name", "Blastgate",
         "--icon", str(PACKAGING / "blastgate.ico"),
         "--add-data", f"{ROOT / 'blastgate' / 'ui' / 'icons'};blastgate/ui/icons",
         "--add-data", f"{PACKAGING / 'licenses'};licenses",
         "--paths", str(ROOT),
         "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
         "--log-level", "WARN",
         str(ROOT / "run_blastgate.py")])
    return DIST / "Blastgate" / "Blastgate.exe"


def smoke_test(exe: Path) -> None:
    """Start the frozen app with the fake hub; it must render its pages and exit by itself."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        subprocess.run([str(exe), "--demo", "--screenshot", tmp], check=True, timeout=120, env=env)
        shots = sorted(p.name for p in Path(tmp).glob("*.png"))
        if "1_pregled.png" not in shots:
            raise SystemExit(f"Packaged app started but rendered nothing ({shots})")
        print("smoke test OK:", ", ".join(shots))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="override the version baked into this build")
    ap.add_argument("--force", action="store_true", help="overwrite an existing installer of this version")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from blastgate import __version__
    version = args.version or __version__
    setup = DIST / "installer" / f"Blastgate-{version}-Setup.exe"
    if setup.exists() and not args.force:
        raise SystemExit(f"{setup} already exists — bump the version or pass --force")
    iscc = next((p for p in ISCC_PLACES if p.is_file()), None)
    if iscc is None:
        raise SystemExit("Inno Setup 6 (ISCC.exe) not found")

    shutil.rmtree(DIST / "Blastgate", ignore_errors=True)
    try:
        if args.version:
            VERSION_OVERRIDE.write_text(f'VERSION = "{version}"\n', encoding="utf-8")
        exe = freeze()
    finally:
        VERSION_OVERRIDE.unlink(missing_ok=True)
    smoke_test(exe)

    setup.unlink(missing_ok=True)
    run([str(iscc), f"/DAppVersion={version}", "/Qp", str(PACKAGING / "setup.iss")])
    data = setup.read_bytes()
    print(f"\n{setup}\n  {len(data)} bytes\n  sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
