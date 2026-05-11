from __future__ import annotations

import getpass
import os
import queue
import socket
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtCore import Qt
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot

from mipview.control.command_registry import CommandRegistry
from mipview.control.ipc_protocol import handle_json_request
from mipview.control.result import CommandResult
from mipview.control.ipc_protocol import response_json


DISPATCH_TIMEOUT_SECONDS = 30.0


class _CommandDispatcher(QObject):
    request_received = Signal(bytes, object)

    def __init__(self, registry: CommandRegistry) -> None:
        super().__init__()
        self._registry = registry
        self.request_received.connect(
            self._handle_request,
            Qt.ConnectionType.QueuedConnection,
        )

    def dispatch(self, payload: bytes) -> str:
        response_queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self.request_received.emit(payload, response_queue)
        try:
            return response_queue.get(timeout=DISPATCH_TIMEOUT_SECONDS)
        except queue.Empty:
            return response_json(
                None,
                CommandResult(False, "Command dispatch timed out."),
            )

    @Slot(bytes, object)
    def _handle_request(self, payload: bytes, response_queue: object) -> None:
        response = handle_json_request(self._registry, payload)
        if isinstance(response_queue, queue.Queue):
            response_queue.put(response)


class MipViewIpcServer:
    """Unix-domain-socket server for newline-delimited MipView command JSON."""

    def __init__(
        self,
        registry: CommandRegistry,
        socket_path: str | Path | None = None,
    ) -> None:
        self._registry = registry
        self._socket_path = Path(socket_path) if socket_path is not None else default_socket_path()
        self._dispatcher = _CommandDispatcher(registry)
        self._server_socket: socket.socket | None = None
        self._server_thread: threading.Thread | None = None
        self._client_threads: set[threading.Thread] = set()
        self._client_sockets: set[socket.socket] = set()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._owns_socket_file = False

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def is_running(self) -> bool:
        thread = self._server_thread
        return thread is not None and thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return

            self._prepare_socket_path()
            server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server_socket.bind(str(self._socket_path))
                try:
                    os.chmod(self._socket_path, 0o600)
                except OSError:
                    pass
                server_socket.listen()
                server_socket.settimeout(0.1)
            except OSError:
                server_socket.close()
                raise

            self._server_socket = server_socket
            self._owns_socket_file = True
            self._stop_event.clear()
            self._server_thread = threading.Thread(
                target=self._serve,
                name="MipViewIpcServer",
                daemon=True,
            )
            self._server_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            server_socket = self._server_socket
            self._server_socket = None
            client_sockets = list(self._client_sockets)

        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass

        for client_socket in client_sockets:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client_socket.close()
            except OSError:
                pass

        server_thread = self._server_thread
        if server_thread is not None and server_thread.is_alive():
            server_thread.join(timeout=2.0)

        for client_thread in list(self._client_threads):
            if client_thread.is_alive():
                client_thread.join(timeout=2.0)

        if self._owns_socket_file:
            try:
                self._socket_path.unlink()
            except FileNotFoundError:
                pass
            self._owns_socket_file = False

    def _serve(self) -> None:
        while not self._stop_event.is_set():
            server_socket = self._server_socket
            if server_socket is None:
                return
            try:
                client_socket, _ = server_socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return

            client_thread = threading.Thread(
                target=self._handle_client,
                args=(client_socket,),
                name="MipViewIpcClient",
                daemon=True,
            )
            with self._lock:
                self._client_sockets.add(client_socket)
                self._client_threads.add(client_thread)
            client_thread.start()

    def _handle_client(self, client_socket: socket.socket) -> None:
        try:
            with client_socket:
                client_file = client_socket.makefile("rb")
                try:
                    for line in client_file:
                        if self._stop_event.is_set():
                            break
                        if not line.strip():
                            continue
                        response = self._dispatcher.dispatch(line)
                        client_socket.sendall(response.encode("utf-8") + b"\n")
                finally:
                    client_file.close()
        except OSError:
            pass
        finally:
            current_thread = threading.current_thread()
            with self._lock:
                self._client_sockets.discard(client_socket)
                self._client_threads.discard(current_thread)

    def _prepare_socket_path(self) -> None:
        socket_dir = self._socket_path.parent
        socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(socket_dir, 0o700)
        except OSError:
            pass

        if not self._socket_path.exists():
            return

        if _socket_is_connectable(self._socket_path):
            raise RuntimeError(
                f"IPC socket already in use: {self._socket_path}"
            )
        self._socket_path.unlink()


def default_socket_path() -> Path:
    user = os.environ.get("USER") or getpass.getuser()
    return Path(tempfile.gettempdir()) / f"mipview-{user}" / "session.sock"


def _socket_is_connectable(socket_path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.1)
        probe.connect(str(socket_path))
        return True
    except OSError:
        return False
    finally:
        probe.close()
