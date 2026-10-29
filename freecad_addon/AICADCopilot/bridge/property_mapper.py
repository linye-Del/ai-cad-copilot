"""Restricted JSON property mapping adapted from neka-nat/freecad-mcp (MIT)."""

import FreeCAD as App


def _resolve(doc, name):
    obj = doc.getObject(str(name))
    if obj is None:
        raise ValueError("Referenced object '%s' not found" % name)
    return obj


def set_properties(doc, obj, properties):
    failures = []
    for prop, value in (properties or {}).items():
        try:
            if prop == "ViewObject" and isinstance(value, dict):
                for view_prop, view_value in value.items():
                    if view_prop == "ShapeColor" and isinstance(view_value, (list, tuple)):
                        view_value = tuple(float(v) for v in view_value[:4])
                    setattr(obj.ViewObject, view_prop, view_value)
                continue
            if prop not in getattr(obj, "PropertiesList", []):
                raise ValueError("property is not writable on %s" % obj.TypeId)
            current = getattr(obj, prop)
            if prop == "Placement" and isinstance(value, dict):
                base = value.get("Base", value.get("Position", {}))
                rotation = value.get("Rotation", {})
                axis = rotation.get("Axis", {})
                value = App.Placement(
                    App.Vector(base.get("x", 0), base.get("y", 0), base.get("z", 0)),
                    App.Rotation(App.Vector(axis.get("x", 0), axis.get("y", 0), axis.get("z", 1)),
                                 rotation.get("Angle", 0)),
                )
            elif isinstance(current, App.Vector) and isinstance(value, dict):
                value = App.Vector(value.get("x", 0), value.get("y", 0), value.get("z", 0))
            elif prop in {"Base", "Tool", "Source", "Profile"} and isinstance(value, str):
                value = _resolve(doc, value)
            setattr(obj, prop, value)
        except Exception as exc:
            failures.append("%s: %s" % (prop, exc))
    if failures:
        raise ValueError("Failed to set properties: " + "; ".join(failures))
    return obj

