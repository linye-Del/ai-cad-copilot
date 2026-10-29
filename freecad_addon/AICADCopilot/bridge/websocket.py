"""Qt WebSocket transport used inside the FreeCAD GUI process."""

import json

try:
    from PySide import QtCore, QtWebSockets
except ImportError:
    try:
        from PySide6 import QtCore, QtWebSockets
    except ImportError:
        from PySide2 import QtCore, QtWebSockets


class WebSocketTransport(QtCore.QObject):
    connected = QtCore.Signal()
    disconnected = QtCore.Signal()
    message = QtCore.Signal(dict)
    transport_error = QtCore.Signal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.is_connected = False
        self.socket = QtWebSockets.QWebSocket()
        self.socket.connected.connect(self._connected)
        self.socket.disconnected.connect(self._disconnected)
        self.socket.textMessageReceived.connect(self._message)
        error_signal = getattr(self.socket, "errorOccurred", None)
        if error_signal is None:
            error_signal = getattr(self.socket, "error", None)
        if hasattr(error_signal, "connect"):
            error_signal.connect(self._error)

    def open(self):
        if not self.is_connected:
            self.socket.open(QtCore.QUrl(self.url))

    def close(self):
        self.socket.close()

    def abort(self):
        self.socket.abort()
        self.is_connected = False

    def send(self, payload):
        if not self.is_connected:
            return False
        self.socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))
        return True

    def _connected(self):
        self.is_connected = True
        self.connected.emit()

    def _disconnected(self):
        self.is_connected = False
        self.disconnected.emit()

    def _message(self, raw):
        try:
            payload = json.loads(raw)
        except Exception as exc:
            self.transport_error.emit("Invalid JSON: %s" % exc)
            return
        if isinstance(payload, dict):
            self.message.emit(payload)

    def _error(self, *args):
        self.transport_error.emit("WebSocket error: %s" % (args[0] if args else "unknown"))
