"""JSON-safe FreeCAD inspection adapted from neka-nat/freecad-mcp (MIT)."""

import FreeCAD as App


def serialize_value(value, depth=0):
    if depth > 3:
        return str(value)
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, App.Vector):
        return {"x": value.x, "y": value.y, "z": value.z}
    if isinstance(value, App.Rotation):
        return {"Axis": serialize_value(value.Axis), "Angle": value.Angle}
    if isinstance(value, App.Placement):
        return {"Base": serialize_value(value.Base),
                "Rotation": serialize_value(value.Rotation)}
    if hasattr(value, "TypeId") and hasattr(value, "Name"):
        return {"name": value.Name, "type_id": value.TypeId}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item, depth + 1) for item in value]
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


def serialize_shape(shape):
    if shape is None:
        return None
    try:
        if shape.isNull():
            return {"is_null": True, "solids": 0}
        box = shape.BoundBox
        return {
            "is_null": False,
            "volume": round(float(shape.Volume), 6),
            "area": round(float(shape.Area), 6),
            "vertices": len(shape.Vertexes),
            "edges": len(shape.Edges),
            "faces": len(shape.Faces),
            "solids": len(shape.Solids),
            "bound_box": {
                "x_length": round(float(box.XLength), 6),
                "y_length": round(float(box.YLength), 6),
                "z_length": round(float(box.ZLength), 6),
                "min": [box.XMin, box.YMin, box.ZMin],
                "max": [box.XMax, box.YMax, box.ZMax],
            },
        }
    except Exception as exc:
        return {"error": "invalid shape: %s" % exc}


def _names(items):
    try:
        return [item.Name for item in items if hasattr(item, "Name")]
    except Exception:
        return []


def serialize_object(obj, all_properties=True):
    result = {
        "name": obj.Name,
        "label": obj.Label,
        "type_id": obj.TypeId,
        "parents": _names(getattr(obj, "InList", [])),
        "children": _names(getattr(obj, "OutList", [])),
        "placement": serialize_value(getattr(obj, "Placement", None)),
        "shape": serialize_shape(getattr(obj, "Shape", None)),
        "state": [str(item) for item in getattr(obj, "State", [])],
    }
    for attr in ("Tip", "Profile", "BaseFeature", "Support"):
        if hasattr(obj, attr):
            result[attr.lower()] = serialize_value(getattr(obj, attr))
    if hasattr(obj, "Group"):
        result["group"] = _names(obj.Group)
    if hasattr(obj, "GeometryCount"):
        result["geometry_count"] = int(obj.GeometryCount)
    if hasattr(obj, "ConstraintCount"):
        result["constraint_count"] = int(obj.ConstraintCount)
        constraints = []
        try:
            for index, constraint in enumerate(obj.Constraints):
                constraints.append({
                    "index": index,
                    "type": str(constraint.Type),
                    "value": float(constraint.Value) if hasattr(constraint, "Value") else None,
                    "first": int(constraint.First) if hasattr(constraint, "First") else None,
                })
        except Exception:
            pass
        result["constraints"] = constraints
    if obj.TypeId == "TechDraw::DrawViewPart" and hasattr(obj, "getVisibleEdges"):
        projected_edges = []
        try:
            for index, edge in enumerate(obj.getVisibleEdges(), 1):
                vertices = []
                for vertex in getattr(edge, "Vertexes", []):
                    vertices.append(serialize_value(vertex.Point))
                projected_edges.append({
                    "index": index,
                    "reference": "Edge%d" % index,
                    "length": round(float(edge.Length), 6),
                    "curve_type": str(getattr(getattr(edge, "Curve", None), "TypeId", "")),
                    "vertices": vertices,
                })
        except Exception as exc:
            projected_edges = [{"error": str(exc)}]
        result["projected_edges"] = projected_edges
        result["projection_methods"] = [
            name for name in dir(obj)
            if any(token in name.casefold() for token in ("vertex", "vertice", "edge", "geom"))
        ]
    if obj.TypeId == "TechDraw::DrawViewDimension":
        try:
            result["measured_value"] = float(obj.getDimValue())
        except Exception as exc:
            result["measured_value_error"] = str(exc)
        try:
            result["linear_points"] = [serialize_value(point)
                                       for point in obj.getLinearPoints()]
        except Exception as exc:
            result["linear_points_error"] = str(exc)
        result["dimension_methods"] = [name for name in dir(obj)
                                       if any(token in name.casefold()
                                              for token in ("point", "bound", "box", "extent"))]
    if all_properties:
        properties = {}
        for prop in getattr(obj, "PropertiesList", []):
            try:
                properties[prop] = serialize_value(getattr(obj, prop))
            except Exception as exc:
                properties[prop] = "<error: %s>" % exc
        result["properties"] = properties
    try:
        view = obj.ViewObject
        result["view"] = {
            "visibility": bool(view.Visibility),
            "transparency": int(getattr(view, "Transparency", 0)),
            "shape_color": serialize_value(getattr(view, "ShapeColor", None)),
        }
        result["view_properties"] = {
            name: serialize_value(getattr(view, name))
            for name in getattr(view, "PropertiesList", [])
            if any(token in name.casefold() for token in ("center", "line", "mark"))
        }
    except Exception:
        result["view"] = {}
    return result


def serialize_document(doc, all_properties=False):
    if doc is None:
        return {"document": "", "label": "", "file_name": "", "objects": []}
    return {
        "document": doc.Name,
        "label": doc.Label,
        "file_name": doc.FileName,
        "undo_count": doc.UndoCount,
        "redo_count": doc.RedoCount,
        "tip": getattr(getattr(doc, "Tip", None), "Name", ""),
        "objects": [serialize_object(obj, all_properties) for obj in doc.Objects],
    }
