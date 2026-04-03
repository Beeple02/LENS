"""Entry point for LENS."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    from lens.config import ensure_dirs
    from lens.db.store import init_db

    ensure_dirs()
    init_db()

    if len(sys.argv) > 1:
        # Delegate to CLI
        from lens.cli import app
        app()
        return

    # Launch Qt desktop app
    import os
    # Use offscreen platform if no display available (CI/testing)
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        if sys.platform != "darwin" and sys.platform != "win32":
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from lens.config import load_config
    from lens.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("LENS")
    app.setOrganizationName("LENS")
    app.setStyle("Fusion")  # Base style to override completely

    # Load global stylesheet
    qss_path = Path(__file__).parent / "ui" / "stylesheet.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text())

    config = load_config()
    window = MainWindow(config)
    window.resize(1400, 900)
    window.setMinimumSize(1100, 700)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
