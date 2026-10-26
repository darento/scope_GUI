"""Entry point: ``uv run scope-gui`` or ``python -m scope_gui``."""

import ctypes
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .settings import load_last_address, log_dir
from .ui.main_window import MainWindow

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
ICON = Path(__file__).with_name("icon.svg")
APP_ID = "oncovision.scope_gui"


def setup_logging() -> None:
    handler = RotatingFileHandler(
        log_dir() / "scope_gui.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Connection events and errors are always logged (FR-020). Logging every query (~250 lines/s
    # while live) would rotate the history away within minutes, so it is opt-in.
    if os.environ.get("SCOPE_GUI_DEBUG"):
        logging.getLogger("scope_gui.driver").setLevel(logging.DEBUG)


def setup_application(app: QApplication, name: str, app_id: str = APP_ID) -> None:
    """Name and icon of every window; on Windows also the taskbar's, which otherwise shows the
    Python interpreter's icon and groups the app with other Python programs."""
    app.setApplicationName(name)
    app.setWindowIcon(QIcon(str(ICON)))
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def main() -> int:
    setup_logging()
    logging.getLogger(__name__).info("scope_gui starting")
    app = QApplication(sys.argv)
    setup_application(app, "Scope GUI")
    window = MainWindow(load_last_address())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
