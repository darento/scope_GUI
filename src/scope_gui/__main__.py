"""Entry point: ``uv run scope-gui`` or ``python -m scope_gui``."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from .settings import load_last_address, log_dir
from .ui.main_window import MainWindow

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def setup_logging() -> None:
    handler = RotatingFileHandler(
        log_dir() / "scope_gui.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Every command sent to the scope is recorded (FR-020).
    logging.getLogger("scope_gui.driver").setLevel(logging.DEBUG)


def main() -> int:
    setup_logging()
    logging.getLogger(__name__).info("scope_gui starting")
    app = QApplication(sys.argv)
    app.setApplicationName("Scope GUI")
    window = MainWindow(load_last_address())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
