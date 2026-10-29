"""AI CAD Copilot FreeCAD Workbench and live Agent dock panel."""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

from AICADCopilot.bridge import start_bridge


class CopilotDock(QtWidgets.QDockWidget):
    def __init__(self, bridge, parent=None):
        super().__init__("AI CAD Copilot", parent)
        self.setObjectName("AICADCopilotDock")
        self.bridge = bridge
        root = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(root)

        self.connection = QtWidgets.QLabel("FreeCAD Disconnected")
        self.connection.setStyleSheet("font-weight:bold;color:#b42318;padding:6px")
        self.document = QtWidgets.QLabel("Document: —")
        self.agent_status = QtWidgets.QLabel("Agent: Idle")
        self.history = QtWidgets.QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("Live Agent messages and execution progress")
        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText("例如：创建一个300mm阶梯轴")
        self.send_button = QtWidgets.QPushButton("Send to AI Agent")
        self.box_button = QtWidgets.QPushButton("Create Test Box")
        self.reconnect_button = QtWidgets.QPushButton("Reconnect Backend")

        layout.addWidget(self.connection)
        layout.addWidget(self.document)
        layout.addWidget(self.agent_status)
        layout.addWidget(self.history, 1)
        layout.addWidget(self.query)
        layout.addWidget(self.send_button)
        layout.addWidget(self.box_button)
        layout.addWidget(self.reconnect_button)
        self.setWidget(root)

        self.send_button.clicked.connect(self._send)
        self.query.returnPressed.connect(self._send)
        self.box_button.clicked.connect(self.bridge.request_test_box)
        self.reconnect_button.clicked.connect(self.bridge.reconnect)
        self.bridge.connection_changed.connect(self._connection_changed)
        self.bridge.status_changed.connect(self._status_changed)
        self.bridge.agent_message.connect(self._agent_message)
        self.bridge.live_event.connect(self._live_event)
        self._connection_changed(self.bridge.connected)

    def _send(self):
        text = self.query.text().strip()
        if text and self.bridge.send_user_query(text):
            self.history.appendPlainText("You: " + text)
            self.agent_status.setText("Agent: Planning")
            self.query.clear()

    def _connection_changed(self, online):
        if online:
            self.connection.setText("FreeCAD Connected")
            self.connection.setStyleSheet("font-weight:bold;color:#067647;padding:6px")
        else:
            self.connection.setText("FreeCAD Disconnected")
            self.connection.setStyleSheet("font-weight:bold;color:#b42318;padding:6px")

    def _status_changed(self, status):
        self.document.setText("Document: " + (status.get("active_document") or "—"))

    def _agent_message(self, message):
        self.agent_status.setText("Agent: " + ("Completed" if message.get("ok") else "Error"))
        self.history.appendPlainText("AI: " + str(message.get("message") or message.get("error") or message))

    def _live_event(self, event):
        if event.get("event") == "plan_progress":
            self.agent_status.setText("Agent: %s (%s/%s)" %
                                      (event.get("op"), event.get("completed"), event.get("total")))


class ShowPanelCommand:
    def GetResources(self):
        return {"MenuText": "Show AI CAD Copilot", "ToolTip": "Show the Live Agent panel"}

    def Activated(self):
        panel = ensure_dock()
        panel.show()
        panel.raise_()


class ReconnectCommand:
    def GetResources(self):
        return {"MenuText": "Reconnect Backend", "ToolTip": "Reconnect the Live FreeCAD bridge"}

    def Activated(self):
        start_bridge().reconnect()


class AICADCopilotWorkbench(Gui.Workbench):
    MenuText = "AI CAD Copilot"
    ToolTip = "Natural-language mechanical design in the running FreeCAD GUI"

    def Initialize(self):
        register_commands()
        commands = ["AICADCopilot_ShowPanel", "AICADCopilot_Reconnect"]
        self.appendToolbar("AI CAD Copilot", commands)
        self.appendMenu("AI CAD Copilot", commands)

    def Activated(self):
        start_services()

    def GetClassName(self):
        return "Gui::PythonWorkbench"


_registered = False
_dock = None


def register_commands():
    global _registered
    if _registered:
        return
    Gui.addCommand("AICADCopilot_ShowPanel", ShowPanelCommand())
    Gui.addCommand("AICADCopilot_Reconnect", ReconnectCommand())
    _registered = True


def _right_dock_area():
    try:
        return QtCore.Qt.DockWidgetArea.RightDockWidgetArea
    except AttributeError:
        return QtCore.Qt.RightDockWidgetArea


def ensure_dock():
    global _dock
    if _dock is None:
        bridge = start_bridge()
        _dock = CopilotDock(bridge, Gui.getMainWindow())
        Gui.getMainWindow().addDockWidget(_right_dock_area(), _dock)
    return _dock


def ensure_model_tree():
    """Keep FreeCAD's native Combo View visible for the parametric tree."""
    window = Gui.getMainWindow()
    combo = None
    for object_name in ("Model", "Combo View"):
        combo = window.findChild(QtWidgets.QDockWidget, object_name)
        if combo is not None:
            break
    if combo is None:
        for candidate in window.findChildren(QtWidgets.QDockWidget):
            if candidate.objectName() in {"Model", "Combo View"} or candidate.windowTitle() in {
                "Model", "模型", "Combo View", "组合视图",
            }:
                combo = candidate
                break
    if combo is None:
        for candidate in window.findChildren(QtWidgets.QWidget):
            if candidate.objectName() in {"Model", "Combo View"}:
                combo = candidate
                break
    for action in window.findChildren(QtCore.QObject):
        if not all(hasattr(action, method) for method in ("text", "isCheckable", "isChecked", "trigger")):
            continue
        label = str(action.text() or "").replace("&", "").strip()
        if label in {"Model", "模型", "Combo View", "组合视图"} and action.isCheckable() and not action.isChecked():
            action.trigger()
            break
    if combo is not None:
        combo.show()
        combo.raise_()
    return combo


def start_services():
    register_commands()
    bridge = start_bridge()
    ensure_model_tree()
    QtCore.QTimer.singleShot(750, ensure_model_tree)
    QtCore.QTimer.singleShot(2000, ensure_model_tree)
    dock = ensure_dock()
    dock.show()
    return bridge, dock
