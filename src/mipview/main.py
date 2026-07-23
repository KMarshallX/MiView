from __future__ import annotations

import signal
import sys
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mipview.control import CommandRegistry
from mipview.control import MipViewController
from mipview.control import MipViewIpcServer
from mipview.ui.main_window import MainWindow


def main() -> int:
    _initialize_vispy_backend()
    app = QApplication(sys.argv)
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)

    signal_pump_timer = QTimer()
    signal_pump_timer.setInterval(100)
    signal_pump_timer.timeout.connect(lambda: None)
    signal_pump_timer.start()

    window = MainWindow()
    ipc_server = _start_ipc_server(window)
    window.show()
    if _smoke_test_enabled():
        QTimer.singleShot(50, app.quit)
    try:
        return app.exec()
    finally:
        if ipc_server is not None:
            ipc_server.stop()
        signal_pump_timer.stop()
        signal.signal(signal.SIGINT, previous_sigint_handler)


def _start_ipc_server(window: MainWindow) -> MipViewIpcServer | None:
    controller = MipViewController(window)
    registry = CommandRegistry(controller)
    ipc_server = MipViewIpcServer(registry)
    try:
        ipc_server.start()
    except (OSError, RuntimeError) as exc:
        print(f"Warning: MipView IPC server failed to start: {exc}", file=sys.stderr)
        return None
    return ipc_server


def _handle_sigint(_signum: int, _frame: object) -> None:
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _smoke_test_enabled() -> bool:
    smoke_value = os.environ.get("MIPVIEW_SMOKE_TEST")
    if smoke_value is None:
        smoke_value = os.environ.get("MIVIEW_SMOKE_TEST", "")
    return smoke_value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _initialize_vispy_backend() -> None:
    """Select the existing PySide6 event loop before any 3D canvas is created."""
    try:
        from vispy import app as vispy_app

        vispy_app.use_app("pyside6")
    except Exception as exc:
        # The GUI remains usable in triplanar-only mode; activation reports the
        # actionable renderer error inside the 3D Volume toolbox.
        print(f"Warning: VisPy backend initialization failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
