"""Stage a release: collect the files, hash them, write the update manifest.

The apps read releases/manifest.json from the main branch; it points at the
assets of a GitHub release. Nothing here talks to GitHub — the script prints
the commands, so publishing stays a separate, deliberate step.

  python tools/make_release.py --tag v1.5.1 \
      --firmware firmware/hub-wt32/.pio/build/wt32_s1_eth01/firmware.bin --fw-version 1.5.1 \
      --apk-dir <folder with app-<abi>-release.apk> --app-version 2.4.0 \
      --fw-notes "..." --app-notes "..." --out <staging folder> [--write-manifest]

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


def asset(path, name, tag, out):
    data = open(path, "rb").read()
    shutil.copyfile(path, os.path.join(out, name))
    return {
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{name}",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--firmware", required=True)
    ap.add_argument("--fw-version", required=True)
    ap.add_argument("--fw-notes", default="")
    ap.add_argument("--min-prev", default="1.2.0", help="oldest hub firmware that may update to this one")
    ap.add_argument("--apk-dir", required=True)
    ap.add_argument("--app-version", required=True)
    ap.add_argument("--app-notes", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--write-manifest", action="store_true", help="also overwrite releases/manifest.json")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    fw = asset(a.firmware, "firmware.bin", a.tag, a.out)
    apks = {}
    for abi in ABIS:
        src = os.path.join(a.apk_dir, f"app-{abi}-release.apk")
        apks[abi] = asset(src, f"blastgate-mobile-{a.app_version}-{abi}.apk", a.tag, a.out)

    manifest = {
        "version": a.fw_version,
        **fw,
        "minPrevVersion": a.min_prev,
        "changelog": a.fw_notes.replace("\\n", "\n"),
        "app": {"version": a.app_version, "changelog": a.app_notes.replace("\\n", "\n"), "apks": apks},
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if a.write_manifest:
        with open(os.path.join(HERE, "releases", "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
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
