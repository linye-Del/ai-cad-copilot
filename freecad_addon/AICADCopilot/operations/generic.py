"""Auditable generic FreeCAD object operations for novel parts."""

import FreeCAD as App

from AICADCopilot.bridge.object_validation import require_valid
from AICADCopilot.bridge.property_mapper import set_properties
from AICADCopilot.bridge.security import safe_name
from AICADCopilot.bridge.serialization import serialize_document, serialize_object
from AICADCopilot.bridge.view_manager import capture_view
from AICADCopilot.operations.document import current_document, refresh_view


def create_object(params, context):
    doc = current_document(context)
    type_id = str(params.get("type_id") or params.get("type") or "")
    if not type_id or not any(type_id.startswith(prefix) for prefix in (
            "App::", "Part::", "PartDesign::", "Sketcher::", "TechDraw::")):
        raise ValueError("Unsupported FreeCAD object type: %s" % type_id)
    name = safe_name(params.get("name"), "Object")
    container_name = str(params.get("container") or "").lstrip("$")
    container = context.get(container_name) or doc.getObject(container_name)
    if container is not None and hasattr(container, "newObject"):
        obj = container.newObject(type_id, name)
    else:
        obj = doc.addObject(type_id, name)
    if params.get("label"):
        obj.Label = str(params["label"])[:128]
    set_properties(doc, obj, params.get("properties") or {})
    doc.recompute()
    require_valid(obj)
    refresh_view()
    return serialize_object(obj)


def inspect_object(params, context):
    doc = current_document(context)
    name = str(params.get("name") or params.get("object_name") or "")
    obj = doc.getObject(name)
    if obj is None:
        raise KeyError("Object '%s' not found in '%s'" % (name, doc.Name))
    return serialize_object(obj, all_properties=True)


def edit_object(params, context):
    doc = current_document(context)
    name = str(params.get("name") or params.get("object_name") or "")
    obj = doc.getObject(name)
    if obj is None:
        raise KeyError("Object '%s' not found in '%s'" % (name, doc.Name))
    set_properties(doc, obj, params.get("properties") or {})
    if params.get("label") is not None:
        obj.Label = str(params["label"])[:128]
    doc.recompute()
    require_valid(obj)
    refresh_view()
    return serialize_object(obj)


def delete_object(params, context):
    doc = current_document(context)
    name = str(params.get("name") or params.get("object_name") or "")
    obj = doc.getObject(name)
    if obj is None:
        raise KeyError("Object '%s' not found in '%s'" % (name, doc.Name))
    dependents = [item.Name for item in getattr(obj, "InList", [])]
    if dependents and not bool(params.get("force", False)):
        raise RuntimeError("Object '%s' has dependents: %s" % (name, ", ".join(dependents)))
    doc.removeObject(name)
    doc.recompute()
    refresh_view()
    return {"deleted": name, "dependents": dependents, "document": doc.Name}


def get_objects(params, context):
    doc = current_document(context)
    return serialize_document(doc, bool(params.get("all_properties", False)))


def get_view(params, context):
    return capture_view(
        str(params.get("view_name") or "Isometric"),
        params.get("width"), params.get("height"), params.get("focus_object"),
    )

