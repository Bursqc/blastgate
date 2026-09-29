"""Dev helper: render each page (and a machine dialog) to PNG, then quit. Used with --demo --screenshot DIR."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def schedule_screenshots(win, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    steps = []

    def page(idx: int, name: str):
        def run():
            win.show_page(idx)
            QTimer.singleShot(400, lambda: win.grab().save(str(out / f"{name}.png")))
        return run

    def dialog():
        nodes = win.ctl.status.get("nodes", [])
        if nodes:
            dlg = win.open_node(nodes[0]["id"])
            dlg.resize(700, 900)
            QTimer.singleShot(600, lambda: dlg.grab().save(str(out / "5_masina.png")))

    def overdrive():
        if win.ctl.demo_hub:
            for n in win.ctl.demo_hub.nodes:     # overdrive auto-exits while a machine runs
                n["running"], n["value"], n["next_toggle"] = False, 3.0, float("inf")
            win.ctl.demo_hub.toggle_overdrive()
        for d in list(win._dialogs.values()):
            d.close()
        win.show_page(0)
        QTimer.singleShot(1400, lambda: win.grab().save(str(out / "6_rucni_rezim.png")))

    steps = [page(0, "1_pregled"), page(1, "2_sistem"), page(2, "3_dogadjaji"), page(3, "4_podesavanja"),
             dialog, overdrive, lambda: None, QApplication.quit]
    for i, fn in enumerate(steps):
        QTimer.singleShot(6000 + i * 1500, fn)
