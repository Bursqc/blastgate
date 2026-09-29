"""
Blastgate desktop (Qt) — run with:  python -m blastgate          (real hub)
                                    python -m blastgate --demo   (fake hub, no hardware)
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from blastgate.constants import APP_VERSION, LOG_PATH  # noqa: E402
from blastgate.logging_config import setup_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="blastgate")
    parser.add_argument("--demo", action="store_true", help="lažni hub sa 6 mašina, bez hardvera")
    parser.add_argument("--screenshot", metavar="DIR", help=argparse.SUPPRESS)  # dev: save page PNGs and exit
    args = parser.parse_args()

    logger = setup_logging("INFO", LOG_PATH, console=True)
    logger.info("Blastgate v%s (Qt)%s", APP_VERSION, " — DEMO" if args.demo else "")

    if args.demo:
        # Demo must never touch the real config file
        import blastgate.config as config_mod
        config_mod.CFG_PATH = Path(tempfile.gettempdir()) / "blastgate_demo_config.json"

    from PySide6.QtWidgets import QApplication

    from blastgate.config import load_config
    from blastgate.ui.controller import Controller
    from blastgate.ui.main_window import MainWindow, apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Blastgate")
    cfg = load_config()
    if cfg.theme not in ("dark", "light"):
        cfg.theme = "dark"            # old tk theme names ("darkly", ...)
    apply_theme(app, cfg)
    ctl = Controller(cfg, demo=args.demo)
    win = MainWindow(ctl)
    win.show()
    if args.screenshot:
        from blastgate.ui.shots import schedule_screenshots
        schedule_screenshots(win, Path(args.screenshot))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
