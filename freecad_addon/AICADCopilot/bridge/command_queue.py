"""Serialize backend commands onto the FreeCAD GUI event loop."""

from collections import deque

from AICADCopilot.bridge.dispatch_health import DispatchHealth

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore


class CommandQueue(QtCore.QObject):
    def __init__(self, handler, parent=None):
        super().__init__(parent)
        self.handler = handler
        self.items = deque()
        self.running = False
        self.health = DispatchHealth()

    def submit(self, message):
        if len(self.items) >= 100:
            raise RuntimeError("FreeCAD command queue is full")
        self.items.append(message)
        if not self.running:
            self.running = True
            QtCore.QTimer.singleShot(0, self._run_next)

    def _run_next(self):
        if not self.items:
            self.running = False
            return
        app = QtCore.QCoreApplication.instance()
        try:
            from PySide import QtWidgets
        except ImportError:
            try:
                from PySide6 import QtWidgets
            except ImportError:
                from PySide2 import QtWidgets
        if (QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton
                or QtWidgets.QApplication.activePopupWidget() is not None
                or QtWidgets.QApplication.activeModalWidget() is not None):
            QtCore.QTimer.singleShot(100, self._run_next)
            return
        message = self.items.popleft()
        task_id = str(message.get("request_id", ""))
        operation = str(message.get("action", "GUI operation"))
        self.health.start(task_id, operation)
        error = ""
        try:
            self.handler(message)
        except Exception as exc:
            error = "%s: %s" % (type(exc).__name__, exc)
            raise
        finally:
            self.health.finish(task_id, error)
        QtCore.QTimer.singleShot(0, self._run_next)

    def status(self):
        return self.health.snapshot(len(self.items))
