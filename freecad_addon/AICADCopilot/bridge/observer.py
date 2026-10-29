"""Observe live FreeCAD document and selection changes."""

import FreeCAD as App
import FreeCADGui as Gui


class DocumentObserver:
    def __init__(self, callback):
        self.callback = callback

    def _emit(self, event, **data):
        self.callback({"event": event, **data})

    def slotCreatedDocument(self, doc):
        self._emit("document_created", document=doc.Name)

    def slotDeletedDocument(self, doc):
        self._emit("document_deleted", document=getattr(doc, "Name", ""))

    def slotActivatedDocument(self, doc):
        self._emit("document_activated", document=doc.Name)

    def slotCreatedObject(self, obj):
        self._emit("object_created", document=obj.Document.Name, object=obj.Name,
                   label=obj.Label, type_id=obj.TypeId)

    def slotDeletedObject(self, obj):
        self._emit("object_deleted", object=getattr(obj, "Name", ""))

    def slotChangedObject(self, obj, prop):
        if prop in {"Label", "Shape", "Visibility", "Tip", "Length", "Radius", "Angle"}:
            self._emit("object_changed", document=obj.Document.Name,
                       object=obj.Name, property=prop)


class SelectionObserver:
    def __init__(self, callback):
        self.callback = callback

    def addSelection(self, document, obj, sub, position):
        self.callback({"event": "selection_changed", "document": document,
                       "object": obj, "subelement": sub})

    def clearSelection(self, document):
        self.callback({"event": "selection_cleared", "document": document})


def install_observers(callback):
    document = DocumentObserver(callback)
    selection = SelectionObserver(callback)
    App.addDocumentObserver(document)
    Gui.Selection.addObserver(selection)
    return document, selection
