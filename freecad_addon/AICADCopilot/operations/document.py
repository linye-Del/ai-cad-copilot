"""Document-level operations executed inside the running FreeCAD process."""

import os

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

from AICADCopilot.bridge.security import safe_name, validate_output_path


def unique_document_name(requested):
    base = safe_name(requested, "AICADCopilot")
    name = base
    index = 1
    while name in App.listDocuments():
        index += 1
        name = "%s_%d" % (base, index)
    return name


def create_document(params, context):
    name = unique_document_name(params.get("name"))
    doc = App.newDocument(name)
    label = str(params.get("label") or params.get("name") or name)[:128]
    doc.Label = label
    context["document"] = doc
    return doc


def active_document(params, context):
    doc = App.ActiveDocument
    if doc is None:
        if params.get("create_if_missing", True):
            return create_document(params, context)
        raise RuntimeError("No active FreeCAD document")
    context["document"] = doc
    return doc


def current_document(context):
    doc = context.get("document") or App.ActiveDocument
    if doc is None:
        raise RuntimeError("No active FreeCAD document")
    return doc


def refresh_view():
    if hasattr(Gui, "activeDocument") and Gui.activeDocument() is not None:
        try:
            view = Gui.activeDocument().activeView()
            if hasattr(view, "viewAxonometric"):
                view.viewAxonometric()
            if hasattr(view, "fitAll"):
                view.fitAll()
        except Exception:
            # A TechDraw MDI page is not a 3D view.  Model data has already
            # been recomputed, so a drawing tab must not make an operation fail.
            pass
    if hasattr(Gui, "updateGui"):
        Gui.updateGui()


def _walk_model(model, parent=None):
    parent = parent or QtCore.QModelIndex()
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        yield index
        yield from _walk_model(model, index)


def _expand_model_tree(doc=None):
    window = Gui.getMainWindow()
    for tree in window.findChildren(QtWidgets.QTreeView):
        model = tree.model()
        if doc is None or model is None:
            tree.expandAll()
            continue
        target = None
        for index in _walk_model(model):
            if str(model.data(index) or "") in {doc.Label, doc.Name}:
                target = index
                break
        if target is not None:
            tree.collapseAll()
            tree.setCurrentIndex(target)
            tree.scrollTo(target)
            tree.expandRecursively(target)


def prepare_view(params, context):
    """Select the live model or TechDraw page and prepare it for inspection."""
    doc = current_document(context)
    mode = str(params.get("mode") or "model").lower()
    window = Gui.getMainWindow()

    if mode == "drawing":
        page_name = str(params.get("page") or "").lstrip("$")
        page = (context.get(page_name) or doc.getObject(page_name)) if page_name else None
        if page is None or page.TypeId != "TechDraw::DrawPage":
            pages = [obj for obj in doc.Objects if obj.TypeId == "TechDraw::DrawPage"]
            page = pages[-1] if pages else None
        if page is None:
            raise RuntimeError("No TechDraw page exists in the active Document")
        for candidate in [obj for obj in doc.Objects if obj.TypeId == "TechDraw::DrawPage"]:
            if candidate is not page:
                try:
                    candidate.ViewObject.hide()
                except Exception:
                    pass
        page.ViewObject.show()
    elif mode == "model":
        mdi = window.findChild(QtWidgets.QMdiArea)
        if mdi is not None:
            candidates = [sub for sub in mdi.subWindowList()
                          if doc.Label in sub.windowTitle() and "Drawing" not in sub.windowTitle()]
            if candidates:
                mdi.setActiveSubWindow(candidates[0])
        refresh_view()
    else:
        raise ValueError("Unsupported GUI view mode: %s" % mode)

    _expand_model_tree(doc)
    window.show()
    window.raise_()
    window.activateWindow()
    Gui.updateGui()
    return {"mode": mode, "document": doc.Name}


def capture_gui(params, context):
    """Capture the actual FreeCAD main window from inside its GUI process."""
    path = validate_output_path(params.get("path"), {".png"})
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    window = Gui.getMainWindow()
    _expand_model_tree(App.ActiveDocument)
    window.show()
    window.raise_()
    window.activateWindow()
    Gui.updateGui()
    pixmap = window.grab()
    if pixmap.isNull() or not pixmap.save(path, "PNG"):
        raise RuntimeError("FreeCAD GUI screenshot failed")
    return {"path": path, "width": pixmap.width(), "height": pixmap.height()}


def undo(params, context):
    doc = current_document(context)
    if not doc.UndoCount:
        raise RuntimeError("Active Document has no undo transaction")
    doc.undo()
    doc.recompute()
    refresh_view()
    return {"document": doc.Name, "undo_count": doc.UndoCount, "redo_count": doc.RedoCount}


def redo(params, context):
    doc = current_document(context)
    if not doc.RedoCount:
        raise RuntimeError("Active Document has no redo transaction")
    doc.redo()
    doc.recompute()
    refresh_view()
    return {"document": doc.Name, "undo_count": doc.UndoCount, "redo_count": doc.RedoCount}


def reopen_document(params, context):
    """Close the active document and reopen a saved FCStd in the same GUI."""
    path = validate_output_path(params.get("path"), {".fcstd"})
    if not os.path.isfile(path):
        raise RuntimeError("FCStd file does not exist: %s" % path)
    current = App.ActiveDocument
    if current is not None:
        App.closeDocument(current.Name)
    doc = App.openDocument(path)
    context.clear()
    context["document"] = doc
    doc.recompute()
    refresh_view()
    return {"document": doc.Name, "path": path, "object_count": len(doc.Objects),
            "types": [obj.TypeId for obj in doc.Objects]}
