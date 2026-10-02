"""Stage a release: collect the files, hash them, write the update manifest.

The apps read releases/manifest.json from the main branch; it points at the
assets of GitHub releases. Nothing here talks to GitHub — the script prints
the commands, so publishing stays a separate, deliberate step.

A release may carry any of the three parts; the parts that are left out keep
pointing at the release they came from:

  python tools/make_release.py --tag v1.5.1 --out <staging folder> \
      --firmware firmware/hub-wt32/.pio/build/wt32_s1_eth01/firmware.bin --fw-version 1.5.1 --fw-notes "..." \
      --apk-dir <folder with app-<abi>-release.apk> --app-version 2.4.0 --app-notes "..." \
      --desktop-setup desktop_qt/dist/installer/Blastgate-2.2.0-Setup.exe --desktop-version 2.2.0 \
      --desktop-notes "..." [--write-manifest]

APKs must be the per-ABI ones (flutter build apk --release --split-per-abi),
all built on the same machine: Android only installs an update signed with the
key of the installed app, and a per-ABI APK has a higher versionCode than a
universal one, so the two kinds must never be mixed.
"""
import argparse
import hashlib
import json
import os
import shutil

REPO = "Bursqc/blastgate"
ABIS = ["arm64-v8a", "armeabi-v7a", "x86_64"]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(HERE, "releases", "manifest.json")


def asset(path, name, tag, out):
    data = open(path, "rb").read()
    shutil.copyfile(path, os.path.join(out, name))
    return {
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{name}",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def notes(text):
    return text.replace("\\n", "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--firmware")
    ap.add_argument("--fw-version")
    ap.add_argument("--fw-notes", default="")
    ap.add_argument("--min-prev", default="1.2.0", help="oldest hub firmware that may update to this one")
    ap.add_argument("--apk-dir")
    ap.add_argument("--app-version")
    ap.add_argument("--app-notes", default="")
    ap.add_argument("--desktop-setup")
    ap.add_argument("--desktop-version")
    ap.add_argument("--desktop-notes", default="")
    ap.add_argument("--write-manifest", action="store_true", help="also overwrite releases/manifest.json")
    a = ap.parse_args()
    for path, version, what in ((a.firmware, a.fw_version, "firmware"), (a.apk_dir, a.app_version, "app"),
                                (a.desktop_setup, a.desktop_version, "desktop")):
        if bool(path) != bool(version):
            ap.error(f"{what}: give both the file and its version")
    if not (a.firmware or a.apk_dir or a.desktop_setup):
        ap.error("nothing to release")

    os.makedirs(a.out, exist_ok=True)
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)                      # parts not released now stay as they are

    if a.firmware:
        manifest.update({"version": a.fw_version, **asset(a.firmware, "firmware.bin", a.tag, a.out),
                         "minPrevVersion": a.min_prev, "changelog": notes(a.fw_notes)})
    if a.apk_dir:
        manifest["app"] = {"version": a.app_version, "changelog": notes(a.app_notes), "apks": {
            abi: asset(os.path.join(a.apk_dir, f"app-{abi}-release.apk"),
                       f"blastgate-mobile-{a.app_version}-{abi}.apk", a.tag, a.out)
            for abi in ABIS}}
    if a.desktop_setup:
        manifest["desktop"] = {"version": a.desktop_version,
                               **asset(a.desktop_setup, f"Blastgate-{a.desktop_version}-Setup.exe", a.tag, a.out),
                               "changelog": notes(a.desktop_notes)}

    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if a.write_manifest:
        with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    files = " ".join(f'"{os.path.join(a.out, n)}"' for n in sorted(os.listdir(a.out)) if n != "manifest.json")
    print("staged in", a.out)
    for n in sorted(os.listdir(a.out)):
        print("  %-48s %10d" % (n, os.path.getsize(os.path.join(a.out, n))))
    print("\nTo publish (in this order, so the manifest never points at missing files):")
    print(f"  1. gh release create {a.tag} --repo {REPO} --title <title> --notes <notes> {files}")
    print("  2. commit + push releases/manifest.json to main" + ("" if a.write_manifest else "  (re-run with --write-manifest)"))


if __name__ == "__main__":
    main()
