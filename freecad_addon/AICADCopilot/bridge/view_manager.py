"""Viewport capture adapted from neka-nat/freecad-mcp (MIT)."""

import base64
import os
import tempfile

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets


_VIEWS = {
    "Isometric": "viewIsometric", "Front": "viewFront", "Top": "viewTop",
    "Right": "viewRight", "Back": "viewBack", "Left": "viewLeft",
    "Bottom": "viewBottom", "Dimetric": "viewDimetric", "Trimetric": "viewTrimetric",
}


def _flush(delay_ms=20):
    Gui.updateGui()
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    flags = QtCore.QEventLoop.ExcludeUserInputEvents | QtCore.QEventLoop.ExcludeSocketNotifiers
    app.processEvents(flags, delay_ms)


def _size(view, width, height):
    try:
        raw = view.getSize()
        vw, vh = int(raw[0]), int(raw[1])
    except Exception:
        vw, vh = 1024, 768
    if width is None and height is None:
        scale = min(1.0, 1024.0 / max(vw, vh, 1))
        return max(1, int(vw * scale)), max(1, int(vh * scale))
    return max(1, int(width or vw)), max(1, int(height or vh))


def capture_view(view_name="Isometric", width=None, height=None, focus_object=None):
    if Gui.ActiveDocument is None:
        raise RuntimeError("No active FreeCAD GUI document")
    view = Gui.ActiveDocument.ActiveView
    if view is None or not hasattr(view, "saveImage"):
        raise RuntimeError("Current view does not support screenshots")
    method = _VIEWS.get(str(view_name))
    if method is None:
        raise ValueError("Unsupported view: %s" % view_name)
    if hasattr(view, method):
        getattr(view, method)()
    obj = App.ActiveDocument.getObject(str(focus_object)) if focus_object and App.ActiveDocument else None
    if obj is not None:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        Gui.SendMsgToActiveView("ViewSelection")
        Gui.Selection.clearSelection()
    else:
        view.fitAll()
    _flush()
    resolved_width, resolved_height = _size(view, width, height)
    fd, path = tempfile.mkstemp(prefix="aicad_view_", suffix=".png")
    os.close(fd)
    try:
        try:
            view.saveImage(path, resolved_width, resolved_height, "Current", "Framebuffer")
        except TypeError:
            view.saveImage(path, resolved_width, resolved_height, "Current")
        with open(path, "rb") as stream:
            encoded = base64.b64encode(stream.read()).decode("ascii")
        return {"mime_type": "image/png", "image_base64": encoded,
                "width": resolved_width, "height": resolved_height,
                "view_name": view_name, "focus_object": focus_object or ""}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

