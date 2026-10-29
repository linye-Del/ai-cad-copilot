"""Sketch and constraint operations."""

import FreeCAD as App
import Part
import Sketcher

from AICADCopilot.bridge.security import safe_name
from AICADCopilot.operations.document import current_document


def _resolve(context, ref):
    key = str(ref or "").lstrip("$")
    obj = context.get(key)
    if obj is None:
        doc = context.get("document") or App.ActiveDocument
        obj = doc.getObject(key) if doc is not None else None
    if obj is None:
        raise KeyError("Unknown CadPlan reference: %s" % ref)
    return obj


def create_sketch(params, context):
    doc = current_document(context)
    body = _resolve(context, params.get("body", "$body"))
    name = safe_name(params.get("name"), "Sketch")
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.Label = str(params.get("label") or name)[:128]
    support_plane = str(params.get("support_plane") or "")
    if support_plane:
        plane = next((item for item in body.Origin.OriginFeatures
                      if item.Name == support_plane or item.Label == support_plane), None)
        if plane is None:
            raise ValueError("Unknown Body support plane: %s" % support_plane)
        sketch.AttachmentSupport = (plane, [""])
        sketch.MapMode = "FlatFace"
    else:
        z_offset = float(params.get("z_offset", 0.0))
        placement = sketch.Placement
        placement.Base = App.Vector(0.0, 0.0, z_offset)
        sketch.Placement = placement
    doc.recompute()
    return sketch


def add_geometry(params, context):
    doc = current_document(context)
    sketch = _resolve(context, params.get("sketch"))
    geometry = params.get("geometry") or []
    indices = []
    for item in geometry:
        kind = str(item.get("type", "")).lower()
        construction = bool(item.get("construction", False))
        if kind == "circle":
            center = item.get("center") or [0.0, 0.0]
            radius = float(item["radius"])
            index = sketch.addGeometry(
                Part.Circle(App.Vector(float(center[0]), float(center[1]), 0.0),
                            App.Vector(0.0, 0.0, 1.0), radius),
                construction,
            )
            indices.append(index)
        elif kind == "line":
            start = item["start"]
            end = item["end"]
            index = sketch.addGeometry(
                Part.LineSegment(App.Vector(float(start[0]), float(start[1]), 0.0),
                                 App.Vector(float(end[0]), float(end[1]), 0.0)),
                construction,
            )
            indices.append(index)
        elif kind in {"polyline", "polygon"}:
            points = item.get("points") or []
            if len(points) < 2:
                raise ValueError("Polyline requires at least two points")
            closed = bool(item.get("closed", kind == "polygon"))
            count = len(points) if closed else len(points) - 1
            for i in range(count):
                start = points[i]
                end = points[(i + 1) % len(points)]
                index = sketch.addGeometry(
                    Part.LineSegment(App.Vector(float(start[0]), float(start[1]), 0.0),
                                     App.Vector(float(end[0]), float(end[1]), 0.0)),
                    construction,
                )
                indices.append(index)
        else:
            raise ValueError("Unsupported sketch geometry: %s" % kind)
    doc.recompute()
    return {"indices": indices, "count": len(indices)}


def add_constraint(params, context):
    doc = current_document(context)
    sketch = _resolve(context, params.get("sketch"))
    constraints = params.get("constraints") or []
    indices = []
    for item in constraints:
        kind = str(item.get("type", ""))
        geometry = int(item.get("geometry", 0))
        if kind in {"Diameter", "Radius", "Distance", "DistanceX", "DistanceY", "Angle"}:
            indices.append(sketch.addConstraint(
                Sketcher.Constraint(kind, geometry, float(item["value"]))))
        elif kind in {"Horizontal", "Vertical", "Block"}:
            indices.append(sketch.addConstraint(Sketcher.Constraint(kind, geometry)))
        elif kind == "Coincident":
            indices.append(sketch.addConstraint(Sketcher.Constraint(
                kind, geometry, int(item["point"]),
                int(item["other_geometry"]), int(item["other_point"]))))
        elif kind == "Equal":
            indices.append(sketch.addConstraint(Sketcher.Constraint(
                kind, geometry, int(item["other_geometry"]))))
        else:
            raise ValueError("Unsupported sketch constraint: %s" % kind)
    doc.recompute()
    return {"indices": indices, "count": len(indices),
            "fully_constrained": bool(getattr(sketch, "FullyConstrained", False))}


def set_constraint(params, context):
    """Change an existing dimensional Sketch constraint by index."""
    doc = current_document(context)
    sketch = _resolve(context, params.get("sketch"))
    index = int(params["index"])
    value = float(params["value"])
    if index < 0 or index >= int(sketch.ConstraintCount):
        raise IndexError("Sketch constraint index out of range: %s" % index)
    constraint = sketch.Constraints[index]
    if str(constraint.Type) not in {
            "Diameter", "Radius", "Distance", "DistanceX", "DistanceY", "Angle"}:
        raise ValueError("Constraint %s is not dimensional (%s)" % (index, constraint.Type))
    unit = " deg" if str(constraint.Type) == "Angle" else " mm"
    sketch.setDatum(index, App.Units.Quantity(("%g" + unit) % value))
    doc.recompute()
    actual = float(sketch.Constraints[index].Value)
    if abs(actual - value) > 1e-6:
        raise RuntimeError("Constraint update did not persist: expected %g, got %g" % (value, actual))
    return {"sketch": sketch.Name, "constraint_index": index,
            "constraint_type": str(constraint.Type), "value": actual}
