from __future__ import annotations

import signal
import sys
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from miview.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)

    signal_pump_timer = QTimer()
    signal_pump_timer.setInterval(100)
    signal_pump_timer.timeout.connect(lambda: None)
    signal_pump_timer.start()

    window = MainWindow()
    window.show()
    if _smoke_test_enabled():
        QTimer.singleShot(50, app.quit)
    try:
        return app.exec()
    finally:
        signal_pump_timer.stop()
        signal.signal(signal.SIGINT, previous_sigint_handler)


def _handle_sigint(_signum: int, _frame: object) -> None:
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _smoke_test_enabled() -> bool:
    return os.environ.get("MIVIEW_SMOKE_TEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


if __name__ == "__main__":
    raise SystemExit(main())
