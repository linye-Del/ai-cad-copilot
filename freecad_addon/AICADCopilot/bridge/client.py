"""Live bridge controller running in the FreeCAD GUI process."""

import datetime
import os
import uuid

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

from AICADCopilot.bridge.command_queue import CommandQueue
from AICADCopilot.bridge.observer import install_observers
from AICADCopilot.bridge.security import validate_backend_url, validate_command
from AICADCopilot.bridge.websocket import WebSocketTransport
from AICADCopilot.operations.executor import LiveOperationExecutor


DEFAULT_BACKEND_WS = "ws://127.0.0.1:8000/ws/freecad"


class LiveBridge(QtCore.QObject):
    connection_changed = QtCore.Signal(bool)
    status_changed = QtCore.Signal(dict)
    agent_message = QtCore.Signal(dict)
    live_event = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instance_id = uuid.uuid4().hex
        self.url = validate_backend_url(os.environ.get("AICAD_BACKEND_WS", DEFAULT_BACKEND_WS))
        self.connecting = False
        self.transport = WebSocketTransport(self.url, self)
        self.transport.connected.connect(self._on_connected)
        self.transport.disconnected.connect(self._on_disconnected)
        self.transport.message.connect(self._on_message)
        self.transport.transport_error.connect(self._on_transport_error)

        self.executor = LiveOperationExecutor(self._send_event)
        self.command_queue = CommandQueue(self._execute_command, self)
        self.document_observer, self.selection_observer = install_observers(self._observed_event)

        self.heartbeat = QtCore.QTimer(self)
        self.heartbeat.setInterval(5000)
        self.heartbeat.timeout.connect(self._send_heartbeat)
        self.reconnect_timer = QtCore.QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.setInterval(3000)
        self.reconnect_timer.timeout.connect(self.connect_backend)

    @property
    def connected(self):
        return self.transport.is_connected

    def connect_backend(self):
        if not self.connected and not self.connecting:
            self.connecting = True
            App.Console.PrintMessage("AI CAD Copilot: connecting to %s\n" % self.url)
            self.transport.open()

    def reconnect(self):
        self.reconnect_timer.stop()
        self.heartbeat.stop()
        self.transport.abort()
        self.connecting = False
        QtCore.QTimer.singleShot(150, self.connect_backend)

    def send_user_query(self, query):
        query = str(query or "").strip()
        if not query:
            return False
        if not self.connected:
            self.agent_message.emit({"ok": False, "message": "Backend disconnected"})
            return False
        return self.transport.send({"type": "user_query", "instance_id": self.instance_id,
                                    "query": query})

    def request_test_box(self):
        return self.send_user_query("创建一个50x30x20mm测试盒子")

    def _on_connected(self):
        self.connecting = False
        self.heartbeat.start()
        self.reconnect_timer.stop()
        App.Console.PrintMessage("AI CAD Copilot: backend connected\n")
        self.connection_changed.emit(True)
        self._send_status("register")

    def _on_disconnected(self):
        self.connecting = False
        self.heartbeat.stop()
        self.connection_changed.emit(False)
        App.Console.PrintWarning("AI CAD Copilot: backend disconnected\n")
        if not self.reconnect_timer.isActive():
            self.reconnect_timer.start()

    def _on_transport_error(self, message):
        self.connecting = False
        App.Console.PrintWarning("AI CAD Copilot: %s\n" % message)

    def _status(self, kind="heartbeat"):
        doc = App.ActiveDocument
        selection = Gui.Selection.getSelection()
        try:
            workbench = Gui.activeWorkbench()
            active_workbench = workbench.name() if workbench else ""
        except Exception:
            active_workbench = ""
        try:
            workbench_registered = "AICADCopilotWorkbench" in Gui.listWorkbenches()
        except Exception:
            workbench_registered = False
        try:
            dock = Gui.getMainWindow().findChild(QtCore.QObject, "AICADCopilotDock")
            dock_visible = bool(dock and dock.isVisible())
        except Exception:
            dock_visible = False
        try:
            combo = Gui.getMainWindow().findChild(QtCore.QObject, "Model")
            if combo is None:
                combo = Gui.getMainWindow().findChild(QtCore.QObject, "Combo View")
            if combo is None:
                for candidate in Gui.getMainWindow().findChildren(QtCore.QObject):
                    if str(candidate.objectName()) in {"Model", "Combo View"}:
                        combo = candidate
                        break
            model_tree_visible = bool(combo and combo.isVisible())
        except Exception:
            model_tree_visible = False
        try:
            dock_widgets = [
                {
                    "object_name": str(widget.objectName()),
                    "title": str(widget.windowTitle()),
                    "visible": bool(widget.isVisible()),
                }
                for widget in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget)
            ]
        except Exception:
            dock_widgets = []
        try:
            modal = QtWidgets.QApplication.activeModalWidget()
            active_modal = str(modal.windowTitle() or modal.objectName()) if modal else ""
        except Exception:
            active_modal = ""
        return {
            "type": kind,
            "freecad_online": True,
            "instance_id": self.instance_id,
            "freecad_version": ".".join(str(part) for part in App.Version()[:3]),
            "active_document": doc.Name if doc else "",
            "active_object": selection[0].Name if selection else "",
            "object_count": len(doc.Objects) if doc else 0,
            "active_workbench": active_workbench,
            "workbench_registered": workbench_registered,
            "dock_visible": dock_visible,
            "model_tree_visible": model_tree_visible,
            "dock_widgets": dock_widgets,
            "gui_dispatch": self.command_queue.status(),
            "active_modal": active_modal,
            "reported_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def _send_status(self, kind="heartbeat"):
        payload = self._status(kind)
        self.transport.send(payload)
        self.status_changed.emit(payload)

    def _send_heartbeat(self):
        self._send_status("heartbeat")

    def _on_message(self, message):
        kind = message.get("type")
        if kind == "command":
            self.command_queue.submit(message)
        elif kind == "agent_message":
            self.agent_message.emit(message)
        elif kind == "hello_ack":
            self._send_status("status")

    def _execute_command(self, message):
        request_id = str(message.get("request_id", ""))
        try:
            action, params = validate_command(message)
            result = self.executor.execute(action, params)
            response = {**self._status("status"), "type": "response",
                        "request_id": request_id, "ok": True, "result": result}
        except Exception as exc:
            App.Console.PrintError("AI CAD Copilot command failed: %s\n" % exc)
            response = {**self._status("status"), "type": "response",
                        "request_id": request_id, "ok": False, "error": str(exc)}
        self.transport.send(response)
        self._send_status("status")

    def _send_event(self, payload):
        message = {"type": "event", "instance_id": self.instance_id, **payload}
        self.transport.send(message)
        self.live_event.emit(message)

    def _observed_event(self, payload):
        self._send_event(payload)
        QtCore.QTimer.singleShot(0, lambda: self._send_status("status"))


_bridge = None


def get_bridge():
    return _bridge


def start_bridge():
    global _bridge
    if _bridge is None:
        _bridge = LiveBridge()
    _bridge.connect_backend()
    return _bridge
