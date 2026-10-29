"""Save and validated TechDraw operations for the current live document."""

from __future__ import annotations

import json
import math
import os
import re

import FreeCAD as App
import FreeCADGui as Gui

from AICADCopilot.bridge.security import safe_name, validate_output_path
from AICADCopilot.drawing.layout_engine import DrawingLayoutEngine, Rect, STANDARD_SCALES
from AICADCopilot.drawing.rule_engine import MechanicalDrawingRuleEngine
from AICADCopilot.drawing.validator import DrawingValidator


def _yield_gui(milliseconds=250):
    """Let TechDraw's background projection finish without an unbounded wait."""
    try:
        from PySide import QtCore
        loop = QtCore.QEventLoop()
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(int(milliseconds))
        loop.exec_()
    except Exception:
        Gui.updateGui()
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


def save_document(params, context):
    doc = current_document(context)
    path = validate_output_path(params.get("path"), {".fcstd"})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc.recompute()
    doc.saveAs(path)
    return {"path": path, "document": doc.Name}


def _find_template(page_format):
    prefix = "A3" if str(page_format).startswith("A3") else "A4"
    candidates = [
        "Mod/TechDraw/Templates/ISO/%s_Landscape_ISO5457_advanced.svg" % prefix,
        "Mod/TechDraw/Templates/ISO/%s_Landscape_ISO5457_minimal.svg" % prefix,
        "Mod/TechDraw/Templates/ISO/%s_Landscape_blank.svg" % prefix,
    ]
    root = App.getResourceDir()
    for relative in candidates:
        path = os.path.join(root, relative)
        if os.path.isfile(path):
            return path
    raise RuntimeError("FreeCAD TechDraw %s template not found" % prefix)


def _managed_page(page):
    return (getattr(page, "TypeId", "") == "TechDraw::DrawPage" and
            (str(getattr(page, "Label", "")).startswith("AI CAD Copilot") or
             str(getattr(page, "Name", "")) in {"DrawingPage", "AgentDrawingPage"}))


def _remove_managed_drawings(doc):
    removed = []
    pages = [item for item in list(doc.Objects) if _managed_page(item)]
    managed = set()
    for page in pages:
        managed.update(list(getattr(page, "Group", [])))
        managed.update(item for item in list(doc.Objects)
                       if page in list(getattr(item, "InList", [])))
        template = getattr(page, "Template", None)
        if template is not None:
            managed.add(template)

    # Older versions removed DrawPage but missed dimensions because
    # DrawPage.Group is empty for them in FreeCAD 1.1.  Clean only our named
    # orphan TechDraw objects so stale extension lines cannot accumulate.
    for item in list(doc.Objects):
        type_id = str(getattr(item, "TypeId", ""))
        name = str(getattr(item, "Name", ""))
        label = str(getattr(item, "Label", ""))
        owned = (
            (type_id == "TechDraw::DrawViewDimension" and name.startswith("Dim_")) or
            (type_id == "TechDraw::DrawViewPart" and
             label in {"MAIN VIEW", "END VIEW", "AXONOMETRIC"}) or
            (type_id == "TechDraw::DrawViewAnnotation" and name.startswith("DrawingNote")) or
            (type_id == "TechDraw::DrawSVGTemplate" and name.startswith("DrawingTemplate"))
        )
        has_page = any(getattr(parent, "TypeId", "") == "TechDraw::DrawPage"
                       for parent in list(getattr(item, "InList", [])))
        legacy_orphan = (not has_page and (
            (type_id == "TechDraw::DrawViewDimension" and name == "MaximumDiameter") or
            (type_id == "TechDraw::DrawViewPart" and name.startswith("EndView"))))
        if owned or legacy_orphan:
            managed.add(item)

    # Delete dependent dimensions/annotations before their source views.
    priority = {"TechDraw::DrawViewDimension": 0,
                "TechDraw::DrawViewAnnotation": 0,
                "TechDraw::DrawViewPart": 1,
                "TechDraw::DrawSVGTemplate": 3}
    for item in sorted(managed, key=lambda obj: priority.get(obj.TypeId, 2)):
        name = str(item.Name)
        if doc.getObject(name) is not None:
            doc.removeObject(name)
            removed.append(name)
    for page in pages:
        page_name = str(page.Name)
        if doc.getObject(page_name) is not None:
            doc.removeObject(page_name)
            removed.append(page_name)
    if removed:
        doc.recompute()
        Gui.updateGui()
    return removed


def _profile_object(profile):
    if isinstance(profile, (tuple, list)):
        return profile[0] if profile else None
    return profile


def _circle_diameter(profile):
    profile = _profile_object(profile)
    if profile is None:
        return 0.0
    for geometry in getattr(profile, "Geometry", []):
        if hasattr(geometry, "Radius"):
            radius = float(geometry.Radius)
            if radius > 0.0:
                return radius * 2.0
    return 0.0


def _profile_circles(profile):
    profile = _profile_object(profile)
    circles = []
    if profile is None:
        return circles
    for geometry in getattr(profile, "Geometry", []):
        if not hasattr(geometry, "Radius"):
            continue
        center = getattr(geometry, "Center", App.Vector(0.0, 0.0, 0.0))
        circles.append({"diameter": float(geometry.Radius) * 2.0,
                        "x": float(center.x), "y": float(center.y)})
    return circles


def _extract_model_spec(doc, source):
    bbox = source.Shape.BoundBox
    model_bbox = {"x_length": float(bbox.XLength), "y_length": float(bbox.YLength),
                  "z_length": float(bbox.ZLength)}
    extents = sorted(model_bbox.values(), reverse=True)
    overall_length = extents[0]
    maximum_diameter = extents[1]
    segments = []
    for obj in doc.Objects:
        if obj.TypeId != "PartDesign::Pad" or not hasattr(obj, "Length"):
            continue
        length = float(obj.Length)
        diameter = _circle_diameter(getattr(obj, "Profile", None))
        if length > 0.0 and diameter > 0.0:
            segments.append({"name": obj.Name, "length": length, "diameter": diameter})
    if not segments or abs(sum(item["length"] for item in segments) - overall_length) > 0.5:
        segments = [{"name": source.Name, "length": overall_length,
                     "diameter": maximum_diameter}]

    chamfer = next((obj for obj in doc.Objects if obj.TypeId == "PartDesign::Chamfer"), None)
    fillet = next((obj for obj in doc.Objects if obj.TypeId == "PartDesign::Fillet"), None)
    pockets = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Pocket"]
    return {
        "bbox": model_bbox,
        "overall_length": overall_length,
        "maximum_diameter": maximum_diameter,
        "segments": segments,
        "chamfer": float(getattr(chamfer, "Size", 0.0)) if chamfer else 0.0,
        "fillet": float(getattr(fillet, "Radius", 0.0)) if fillet else 0.0,
        "keyway_present": any("key" in (obj.Name + " " + obj.Label).casefold()
                              or "键槽" in (obj.Name + " " + obj.Label) for obj in pockets),
    }


def _part_spec_from_model(doc, source, model_spec, supplied=None):
    if isinstance(supplied, dict) and supplied.get("part_type"):
        return dict(supplied)
    name = (str(doc.Name) + " " + str(doc.Label)).casefold()
    pads = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Pad"]
    pockets = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Pocket"]
    if "flange" in name or "法兰" in name:
        pad = pads[0] if pads else None
        outer = _circle_diameter(getattr(pad, "Profile", None)) if pad else 0.0
        thickness = float(getattr(pad, "Length", model_spec["bbox"]["z_length"])) if pad else float(model_spec["bbox"]["z_length"])
        bore = _circle_diameter(getattr(pockets[0], "Profile", None)) if pockets else 0.0
        hole_circles = (_profile_circles(getattr(pockets[1], "Profile", None))
                        if len(pockets) > 1 else [])
        hole_d = float(hole_circles[0]["diameter"]) if hole_circles else 0.0
        pcd = (2.0 * math.hypot(hole_circles[0]["x"], hole_circles[0]["y"])
               if hole_circles else 0.0)
        return {
            "part_type": "flange", "name": str(doc.Label), "material": "Q235B",
            "total_length_mm": thickness,
            "parameters": {"D": outer, "d": bore, "t": thickness,
                           "n": len(hole_circles), "pcd": pcd, "hole_d": hole_d},
            "features": [], "tolerances": [], "surface_requirements": [],
        }
    if "plate" in name or "板" in name:
        pad = pads[0] if pads else None
        thickness = float(getattr(pad, "Length", model_spec["bbox"]["z_length"])) if pad else float(model_spec["bbox"]["z_length"])
        hole_circles = (_profile_circles(getattr(pockets[0], "Profile", None))
                        if pockets else [])
        hole_d = float(hole_circles[0]["diameter"]) if hole_circles else 0.0
        xs = [item["x"] for item in hole_circles]
        ys = [item["y"] for item in hole_circles]
        length = float(model_spec["bbox"]["x_length"])
        width = float(model_spec["bbox"]["y_length"])
        return {
            "part_type": "plate", "name": str(doc.Label), "material": "Q235B",
            "total_length_mm": thickness,
            "parameters": {"length": length, "width": width, "thickness": thickness,
                           "hole_count": len(hole_circles), "hole_d": hole_d,
                           "margin_x": min(xs) if xs else length / 2.0,
                           "margin_y": min(ys) if ys else width / 2.0},
            "features": [], "tolerances": [], "surface_requirements": [],
        }
    if len(model_spec.get("segments") or []) > 1 or "shaft" in name or "轴" in name:
        features = []
        if model_spec.get("chamfer", 0.0) > 0:
            features.append({"type": "chamfer", "size_mm": model_spec["chamfer"],
                             "source": {"kind": "design_engine",
                                        "detail": "Existing parametric Chamfer feature"}})
        if model_spec.get("fillet", 0.0) > 0:
            features.append({"type": "fillet", "size_mm": model_spec["fillet"],
                             "source": {"kind": "design_engine",
                                        "detail": "Existing parametric Fillet feature"}})
        if model_spec.get("keyway_present"):
            features.append({"type": "keyway", "size_mm": None,
                             "source": {"kind": "design_engine",
                                        "detail": "Existing parametric Pocket feature"}})
        return {
            "part_type": "shaft", "name": str(doc.Label),
            "material": "45钢", "total_length_mm": model_spec["overall_length"],
            "segments": [
                {"diameter_mm": item["diameter"], "length_mm": item["length"],
                 "source": {"kind": "design_engine", "detail": "Existing sketch/pad"}}
                for item in model_spec.get("segments") or []
            ],
            "features": features, "parameters": {}, "tolerances": [],
            "surface_requirements": [],
        }
    return {"part_type": "generic", "name": str(doc.Label), "parameters": {},
            "features": [], "tolerances": [], "surface_requirements": []}


def _dimension_descriptors(spec, strategy=None):
    dimensions = [{"role": "overall_length", "value": spec["overall_length"],
                   "text": "%g" % spec["overall_length"]}]
    segments = list(spec["segments"])
    total = sum(float(item["length"]) for item in segments)
    cumulative = [0.0]
    for segment in segments:
        cumulative.append(cumulative[-1] + float(segment["length"]))
    # Datum/baseline dimensions: locate every shoulder from the left datum.
    # Do not emit the old closed chain 300 + 150 + 2×75.
    for boundary_index in range(1, len(segments)):
        value = cumulative[boundary_index]
        dimensions.append({"role": "shoulder_location_%d" % boundary_index,
                           "value": value, "text": "%g" % value,
                           "boundary_index": boundary_index,
                           "start_fraction": 0.0,
                           "end_fraction": value / total})
    unique_diameters = []
    for index, segment in enumerate(spec["segments"]):
        value = float(segment["diameter"])
        if not any(abs(value - item[0]) < 0.01 for item in unique_diameters):
            unique_diameters.append((value, index))
    unique_diameters.sort()
    for diameter_index, (value, index) in enumerate(unique_diameters, 1):
        role = "diameter_%d" % diameter_index
        dimensions.append({"role": role, "value": value, "text": "Ø%g" % value,
                           "segment_index": index})
    if spec["chamfer"] > 0.0:
        dimensions.append({"role": "chamfer", "value": spec["chamfer"],
                           "text": "C%g" % spec["chamfer"]})
    if spec["fillet"] > 0.0:
        dimensions.append({"role": "radius", "value": spec["fillet"],
                           "text": "R%g" % spec["fillet"]})
    return dimensions


def _part_dimension_descriptors(model_spec, part_spec, strategy):
    part_type = str(part_spec.get("part_type") or "shaft")
    if part_type == "shaft":
        return _dimension_descriptors(model_spec, strategy)
    p = dict(part_spec.get("parameters") or {})
    if part_type == "flange":
        return [
            {"role": "outer_diameter", "value": float(p["D"]), "text": "Ø%g" % p["D"],
             "view": "front", "kind": "circle", "format": "⌀%.0f"},
            {"role": "bore_diameter", "value": float(p["d"]), "text": "Ø%g" % p["d"],
             "view": "front", "kind": "circle", "format": "⌀%.0f"},
            {"role": "thickness", "value": float(p["t"]), "text": "%g" % p["t"],
             "view": "side", "kind": "linear_any"},
            {"role": "bolt_hole_diameter", "value": float(p["hole_d"]),
             "text": "%d×Ø%g" % (int(p["n"]), p["hole_d"]),
             "view": "front", "kind": "circle", "format": "%d×⌀%%.0f" % int(p["n"])},
            {"role": "pitch_circle_diameter", "value": float(p["pcd"]),
             "text": "PCD Ø%g" % p["pcd"], "view": "front", "kind": "circle_centers",
             "feature_diameter": float(p["hole_d"])},
        ]
    if part_type == "plate":
        return [
            {"role": "plate_length", "value": float(p["length"]), "text": "%g" % p["length"],
             "view": "front", "kind": "linear_any"},
            {"role": "plate_width", "value": float(p["width"]), "text": "%g" % p["width"],
             "view": "front", "kind": "linear_any"},
            {"role": "thickness", "value": float(p["thickness"]),
             "text": "%g" % p["thickness"], "view": "side", "kind": "linear_any"},
            {"role": "hole_diameter", "value": float(p["hole_d"]),
             "text": "%d×Ø%g" % (int(p["hole_count"]), p["hole_d"]),
             "view": "front", "kind": "circle",
             "format": "%d×⌀%%.0f" % int(p["hole_count"])},
            {"role": "hole_pitch_x",
             "value": float(p["length"]) - 2.0 * float(p["margin_x"]),
             "text": "%g" % (float(p["length"]) - 2.0 * float(p["margin_x"])),
             "view": "front", "kind": "linear_any"},
            {"role": "hole_pitch_y",
             "value": float(p["width"]) - 2.0 * float(p["margin_y"]),
             "text": "%g" % (float(p["width"]) - 2.0 * float(p["margin_y"])),
             "view": "front", "kind": "linear_any"},
        ]
    return _dimension_descriptors(model_spec, strategy)


def _repair_shaft_finish_interference(doc, source):
    """Keep shoulder fillets from consuming terminal chamfers.

    The original selector treated the new circular edges produced by Chamfer
    as ordinary shoulders.  Applying R1.25 to those edges changed C1 into an
    unrelated 1.2678 projection.  Repair only that demonstrably invalid edge
    selection while preserving both native PartDesign features.
    """
    if getattr(source, "TypeId", "") != "PartDesign::Fillet":
        return {"repaired": False}
    base_value = getattr(source, "Base", None)
    chamfer = base_value[0] if isinstance(base_value, (tuple, list)) and base_value else None
    if chamfer is None or getattr(chamfer, "TypeId", "") != "PartDesign::Chamfer":
        return {"repaired": False}
    chamfer_size = float(getattr(chamfer, "Size", 0.0))
    fillet_radius = float(getattr(source, "Radius", 0.0))
    clearance = max(2.0, chamfer_size + fillet_radius + 0.2)
    shape = chamfer.Shape
    axis = _primary_axis(shape)
    bbox = shape.BoundBox
    limits = ((bbox.XMin, bbox.XMax), (bbox.YMin, bbox.YMax),
              (bbox.ZMin, bbox.ZMax))[axis]
    desired = []
    for edge_index, edge in enumerate(shape.Edges, 1):
        curve = getattr(edge, "Curve", None)
        if float(getattr(curve, "Radius", 0.0)) <= 0.0:
            continue
        center = getattr(edge, "CenterOfMass", None)
        if center is None:
            continue
        location = _coordinate(center, axis)
        if min(abs(location - limits[0]), abs(location - limits[1])) > clearance:
            desired.append("Edge%d" % edge_index)
    current = list(base_value[1]) if len(base_value) > 1 else []
    if not desired or set(current) == set(desired):
        return {"repaired": False, "edges": current}
    source.Base = (chamfer, desired)
    doc.recompute()
    if source.Shape.isNull():
        source.Base = (chamfer, current)
        doc.recompute()
        raise RuntimeError("Fillet/chamfer interference repair produced an empty shape")
    return {"repaired": True, "old_edges": current, "new_edges": desired,
            "terminal_clearance": clearance}


def _set_template_fields(template, doc, source, params, layout):
    fields = dict(template.EditableTexts)
    strategy = dict(layout.get("strategy") or {})
    general_tolerance = strategy.get("general_tolerance")
    general_tolerance_text = (str(general_tolerance.get("value"))
                              if isinstance(general_tolerance, dict) else "")
    replacements = {
        "title": str(params.get("title") or source.Label),
        "supplementary_title_1": "PARAMETRIC PART / LIVE FREECAD",
        "supplementary_title_2": str(strategy.get("drawing_standard") or ""),
        "drawing_number": str(params.get("drawing_number") or (doc.Name + "-001")),
        "revision_index": "A",
        "language_code": "ZH/EN",
        "responsible_department": "Mechanical Design",
        "approval_person": "",
        "creator": "AI CAD Copilot",
        "document_type": "Part drawing",
        "document_status": "MECHANICAL VALIDATED",
        "scale": layout["scale_label"],
        "general_tolerances": general_tolerance_text,
        "part_material": str(params.get("material") or "45钢"),
        "legal_owner_1": "AI CAD Copilot",
        "legal_owner_2": "",
        "legal_owner_3": "",
        "legal_owner_4": "",
    }
    for key, value in replacements.items():
        if key in fields:
            fields[key] = value
    template.EditableTexts = fields


def _set_view_centerlines(view, requirements):
    requirements = set(requirements or [])
    horizontal = bool(requirements & {"horizontal", "horizontal_axis", "hole_centers"})
    vertical = bool(requirements & {"vertical", "hole_centers"})
    arcs = bool(requirements & {"arc_centers", "hole_centers"})
    # The legacy Horiz/VertCenterLine switches render view axes in FreeCAD's
    # coordinate colours in exported PDFs.  Real TechDraw centerlines carry an
    # explicit ISO/GB-style dash-dot format, black colour, thin weight and an
    # extension beyond the outline.
    for owner in (view, getattr(view, "ViewObject", None)):
        if owner is None:
            continue
        if hasattr(owner, "HorizCenterLine"):
            owner.HorizCenterLine = False
        if hasattr(owner, "VertCenterLine"):
            owner.VertCenterLine = False
        if hasattr(owner, "ArcCenterMarks"):
            owner.ArcCenterMarks = arcs
    records = []
    if horizontal or vertical:
        if not hasattr(view, "makeCenterLine"):
            raise RuntimeError("TechDraw build does not expose makeCenterLine")
        for orientation, mode in (("horizontal", 1), ("vertical", 0)):
            if (orientation == "horizontal" and not horizontal) or (
                    orientation == "vertical" and not vertical):
                continue
            tag = view.makeCenterLine(["Face0"], mode)
            centerline = view.getCenterLine(tag)
            old_format = centerline.Format
            if isinstance(old_format, dict):
                centerline.Format = {
                    "style": 4,
                    "weight": 0.18,
                    "color": (0.0, 0.0, 0.0, 1.0),
                    "visible": True,
                }
            else:
                centerline.Format = (4, 0.18, (0.0, 0.0, 0.0, 0.0), True)
            centerline.Extension = 3.0
            records.append({"orientation": orientation, "tag": str(tag),
                            "style": 4, "weight": 0.18,
                            "color": [0.0, 0.0, 0.0, 1.0], "extension": 3.0})
    if not hasattr(view, "AICADCenterlineValidation"):
        view.addProperty("App::PropertyString", "AICADCenterlineValidation", "AI CAD")
    view.AICADCenterlineValidation = json.dumps(records, sort_keys=True)


def _centerline_evidence(views, strategy):
    for item in strategy.get("views", []):
        role = item.get("role")
        required = set(item.get("centerlines") or [])
        if not required:
            continue
        view = views.get(role)
        if view is None:
            return False
        try:
            records = json.loads(str(view.AICADCenterlineValidation))
        except Exception:
            records = []
        by_orientation = {item.get("orientation"): item for item in records}
        horizontal = "horizontal" in by_orientation
        vertical = "vertical" in by_orientation
        owner = getattr(view, "ViewObject", None)
        arcs = bool(getattr(view, "ArcCenterMarks", False) or
                    getattr(owner, "ArcCenterMarks", False))
        if required & {"horizontal", "horizontal_axis", "hole_centers"} and not horizontal:
            return False
        if required & {"vertical", "hole_centers"} and not vertical:
            return False
        if required & {"arc_centers", "hole_centers"} and not arcs:
            return False
    return True


def _centerline_format_evidence(views, strategy):
    for item in strategy.get("views", []):
        if not item.get("centerlines"):
            continue
        view = views.get(item.get("role"))
        if view is None:
            return False
        try:
            records = json.loads(str(view.AICADCenterlineValidation))
        except Exception:
            return False
        if not records:
            return False
        for record in records:
            if int(record.get("style", 0)) != 4:
                return False
            if abs(float(record.get("weight", 0.0)) - 0.18) > 0.001:
                return False
            color = list(record.get("color", []))
            if any(abs(float(value)) > 0.001 for value in color[:3]):
                return False
            if float(record.get("extension", 0.0)) <= 0.0:
                return False
    return True


def _wait_for_projection(doc, page, views):
    page.ViewObject.show()
    for _ in range(20):
        for view in views:
            try:
                view.recompute()
            except Exception:
                pass
        doc.recompute()
        Gui.updateGui()
        _yield_gui(250)
        try:
            if all(list(view.getVisibleEdges()) for view in views):
                return
        except Exception:
            pass
    raise RuntimeError("TechDraw projection geometry did not become ready")


def _projected_view_bbox(view, padding=1.5):
    """Return the real page-space envelope of a projected TechDraw view."""
    bounds = []
    for edge in list(view.getVisibleEdges()) + list(view.getHiddenEdges()):
        try:
            box = edge.BoundBox
            bounds.append((float(box.XMin), float(box.YMin),
                           float(box.XMax), float(box.YMax)))
        except Exception:
            continue
    if not bounds:
        raise RuntimeError("Projected view %s has no measurable geometry" % view.Name)
    left = float(view.X) + min(item[0] for item in bounds) - padding
    bottom = float(view.Y) + min(item[1] for item in bounds) - padding
    right = float(view.X) + max(item[2] for item in bounds) + padding
    top = float(view.Y) + max(item[3] for item in bounds) + padding
    return Rect(left, bottom, right, top)


def _fit_actual_projected_views(doc, views, layout):
    """Observe real view extents and preserve declared projection relations."""
    safe = layout["safe_drawing_bounds"]
    front = views["front"]
    target = layout["views"]["front"]["bbox"]
    front_rect = _projected_view_bbox(front)
    front.X = float(front.X) + target.center_x - front_rect.center_x
    front.Y = float(front.Y) + target.center_y - front_rect.center_y
    doc.recompute()
    _yield_gui(200)
    front_rect = _projected_view_bbox(front)
    if not safe.contains(front_rect):
        raise RuntimeError("Main view leaves safe drawing bounds: %s" % front_rect.as_dict())
    layout["views"]["front"]["bbox"] = front_rect
    placed = [front_rect]
    for role, view in views.items():
        if role == "front":
            continue
        planned = layout["views"][role]
        rect = _projected_view_bbox(view)
        view.X = float(view.X) + planned["bbox"].center_x - rect.center_x
        view.Y = float(view.Y) + planned["bbox"].center_y - rect.center_y
        doc.recompute()
        _yield_gui(200)
        rect = _projected_view_bbox(view)
        relation = str(planned.get("relation") or "auxiliary")
        if relation == "left_of_primary":
            view.X = float(view.X) + (front_rect.left - 8.0 - rect.width / 2.0) - rect.center_x
            view.Y = float(view.Y) + front_rect.center_y - rect.center_y
        elif relation == "below_primary":
            view.X = float(view.X) + front_rect.center_x - rect.center_x
            view.Y = float(view.Y) + (front_rect.bottom - 8.0 - rect.height / 2.0) - rect.center_y
        doc.recompute()
        _yield_gui(200)
        rect = _projected_view_bbox(view)
        if not safe.contains(rect, 0.5) or any(rect.intersects(old, 3.0) for old in placed):
            raise RuntimeError("%s view cannot preserve projection relation inside safe bounds" % role)
        planned["x"], planned["y"] = float(view.X), float(view.Y)
        planned["bbox"] = rect
        placed.append(rect)
    return {name: item["bbox"].as_dict() for name, item in layout["views"].items()}


def _points(view):
    """Return selectable TechDraw vertices using the view's geometry index.

    getVisibleVertexes() is a filtered shape list.  Its Python list position is
    not the stable ``VertexN`` subelement index used by References2D.  The
    TechDraw API exposes getVertexByIndex specifically for that mapping.
    """
    result = []
    visible_count = len(list(view.getVisibleVertexes()))
    for index in range(visible_count + 32):
        selection_name = "Vertex%d" % index
        try:
            vertex = view.getVertexBySelection(selection_name)
            if vertex is None or getattr(vertex, "isNull", lambda: False)():
                continue
            point = getattr(vertex, "Point", vertex)
            result.append({"index": index, "name": selection_name,
                           "x": float(point.x), "y": float(point.y)})
        except Exception:
            continue
    if not result:
        raise RuntimeError("TechDraw did not expose selectable projection vertices")
    return result


def _selectable_edges(view):
    result = []
    visible_count = len(list(view.getVisibleEdges()))
    for index in range(visible_count + 32):
        selection_name = "Edge%d" % index
        try:
            edge = view.getEdgeBySelection(selection_name)
            if edge is None or getattr(edge, "isNull", lambda: False)():
                continue
            result.append({"index": index, "name": selection_name, "edge": edge})
        except Exception:
            continue
    if not result:
        raise RuntimeError("TechDraw did not expose selectable projection edges")
    return result


def _axis_info(points):
    x_span = max(item["x"] for item in points) - min(item["x"] for item in points)
    y_span = max(item["y"] for item in points) - min(item["y"] for item in points)
    return ("x", "y") if x_span >= y_span else ("y", "x")


def _nearest_vertex(points, axis, target, perpendicular, highest=True):
    minimum = min(abs(item[axis] - target) for item in points)
    candidates = [item for item in points if abs(abs(item[axis] - target) - minimum) < 0.01]
    return (max if highest else min)(candidates, key=lambda item: item[perpendicular])


def _referenced_shape(obj, subname):
    match = re.fullmatch(r"(Vertex|Edge)(\d+)", str(subname))
    if not match:
        raise RuntimeError("Unsupported dimension subelement: %s" % subname)
    collection = obj.Shape.Vertexes if match.group(1) == "Vertex" else obj.Shape.Edges
    index = int(match.group(2)) - 1
    if index < 0 or index >= len(collection):
        raise RuntimeError("Dimension subelement is out of range: %s.%s" %
                           (obj.Name, subname))
    return collection[index]


def _measure_from_references(refs, refs3d, kind, measure_type):
    """Validate the exact linked geometry when getDimValue is not exposed.

    Some FreeCAD 1.1 development builds omit DrawViewDimension.getDimValue()
    from the Python wrapper.  Measuring the subshapes held by References2D/3D
    preserves the same association and avoids accepting a formatted string.
    """
    active_refs = refs3d if measure_type == "True" and refs3d else refs
    shapes = []
    for obj, subname in active_refs:
        if measure_type == "True":
            shapes.append(_referenced_shape(obj, subname))
        elif str(subname).startswith("Vertex"):
            shapes.append(obj.getVertexBySelection(str(subname)))
        elif str(subname).startswith("Edge"):
            shapes.append(obj.getEdgeBySelection(str(subname)))
        else:
            raise RuntimeError("Unsupported 2D dimension subelement: %s" % subname)

    # getVertexBySelection/getEdgeBySelection return TopoShapes in model units;
    # they are not the internally scaled TechDraw BaseGeom used by C++.
    # getVertexBySelection/getEdgeBySelection expose model units even though
    # getVisibleEdges() exposes scaled page geometry in FreeCAD 1.1.
    scale = 1.0
    def reference_point(shape):
        if hasattr(shape, "Point"):
            return shape.Point
        curve = getattr(shape, "Curve", None)
        return getattr(curve, "Center", None) or getattr(curve, "Location", None)

    if len(shapes) == 2 and all(reference_point(item) is not None for item in shapes):
        delta = reference_point(shapes[1]).sub(reference_point(shapes[0]))
        if kind == "DistanceX":
            return abs(float(delta.x)) / scale
        if kind == "DistanceY":
            return abs(float(delta.y)) / scale
        return float(delta.Length) / scale
    if len(shapes) == 1 and hasattr(shapes[0], "Curve"):
        edge = shapes[0]
        radius = float(getattr(edge.Curve, "Radius", 0.0))
        if kind == "Radius":
            return radius / scale
        if kind == "Diameter":
            return radius * 2.0 / scale
        vertices = list(edge.Vertexes)
        if len(vertices) == 2:
            delta = vertices[1].Point.sub(vertices[0].Point)
            if kind == "DistanceX":
                return abs(float(delta.x)) / scale
            if kind == "DistanceY":
                return abs(float(delta.y)) / scale
        return float(edge.Length) / scale
    raise RuntimeError("Dimension references do not describe measurable geometry")


def _dimension(page, doc, descriptor, refs, kind, position, format_spec,
               expected, tolerance=None, refs3d=None, measure_type="Projected"):
    name = safe_name("Dim_" + descriptor["role"], "Dimension")
    dim = doc.addObject("TechDraw::DrawViewDimension", name)
    dim.Label = descriptor["text"] + " — associative"
    page.addView(dim)
    dim.Type = kind
    dim.References2D = refs
    if refs3d:
        dim.References3D = refs3d
    if hasattr(dim, "MeasureType"):
        dim.MeasureType = measure_type
    # FreeCAD 1.1 stores DrawViewDimension position in its referenced view's
    # local page coordinate system, unlike DrawViewPart.X/Y which are absolute.
    reference_view = refs[0][0] if refs else None
    origin_x = float(getattr(reference_view, "X", 0.0))
    origin_y = float(getattr(reference_view, "Y", 0.0))
    dim.X = float(position[0]) - origin_x
    dim.Y = float(position[1]) - origin_y
    if hasattr(dim, "FormatSpec"):
        dim.FormatSpec = format_spec
    if tolerance and hasattr(dim, "EqualTolerance"):
        dim.EqualTolerance = False
        if hasattr(dim, "ArbitraryTolerances"):
            dim.ArbitraryTolerances = False
        if hasattr(dim, "OverTolerance"):
            dim.OverTolerance = float(tolerance[0])
        if hasattr(dim, "UnderTolerance"):
            dim.UnderTolerance = float(tolerance[1])
        if hasattr(dim, "FormatSpecOverTolerance"):
            dim.FormatSpecOverTolerance = "%+.3w"
        if hasattr(dim, "FormatSpecUnderTolerance"):
            dim.FormatSpecUnderTolerance = "%+.3w"
    measured = 0.0
    for _ in range(12):
        doc.recompute()
        Gui.updateGui()
        _yield_gui(250)
        try:
            if hasattr(dim, "getDimValue"):
                measured = float(dim.getDimValue())
                if measured <= 0.0:
                    measured = _measure_from_references(refs, refs3d, kind, measure_type)
            else:
                measured = _measure_from_references(refs, refs3d, kind, measure_type)
            state = [str(item) for item in getattr(dim, "State", [])]
            invalid = any("Invalid" in item or "Error" in item for item in state)
            if invalid:
                break
            if measured > 0.0:
                break
        except Exception:
            measured = 0.0
    allowed = max(0.05, abs(float(expected)) * 0.005)
    if measured <= 0.0 or abs(measured - float(expected)) > allowed:
        details = {
            "role": descriptor["role"],
            "references": [str(item[1]) for item in refs],
            "references_3d": [str(item[1]) for item in (refs3d or [])],
            "measure_type": measure_type,
            "type": kind,
            "state": [str(item) for item in getattr(dim, "State", [])],
            "measured": measured,
            "expected": expected,
            "get_dim_value_available": hasattr(dim, "getDimValue"),
        }
        try:
            page.removeView(dim)
        except Exception:
            pass
        doc.removeObject(dim.Name)
        doc.recompute()
        raise RuntimeError("associative dimension validation failed: %s" % details)
    return dim, measured


def _dimension_preferences():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Dimensions")


def _finite_vertex_candidates(points, axis, perpendicular, expected, scale,
                              target_midpoint=None, diameter=False):
    """Rank selectable projected vertex pairs by geometry, never by list index."""
    expected_span = abs(float(expected))
    tolerance = max(0.03, expected_span * 0.004)
    candidates = []
    for index, first in enumerate(points):
        for second in points[index + 1:]:
            axial = abs(float(second[axis]) - float(first[axis]))
            radial = abs(float(second[perpendicular]) - float(first[perpendicular]))
            measured_span = radial if diameter else axial
            orthogonal = axial if diameter else radial
            error = abs(measured_span - expected_span)
            if error > tolerance:
                continue
            midpoint = (float(first[axis]) + float(second[axis])) / 2.0
            target_error = abs(midpoint - float(target_midpoint)) if target_midpoint is not None else 0.0
            # Same axial station for diameters; same silhouette lane for lengths.
            candidates.append((error, target_error, orthogonal,
                               first["name"], second["name"]))
    return sorted(candidates)[:24]


def _projected_vertex_dimension(page, doc, front, descriptor, position,
                                axis, perpendicular, target_midpoint=None,
                                diameter=False, tolerance=None):
    """Create a true References2D dimension against the displayed main view."""
    preferences = _dimension_preferences()
    previous = bool(preferences.GetBool("AutoCorrectRefs", True))
    preferences.SetBool("AutoCorrectRefs", False)
    dim = None
    try:
        points = _points(front)
        candidates = _finite_vertex_candidates(
            points, axis, perpendicular, descriptor["value"], float(front.Scale),
            target_midpoint=target_midpoint, diameter=diameter)
        if not candidates:
            raise RuntimeError("no projected vertex pair matches %s=%g" %
                               (descriptor["role"], descriptor["value"]))
        kind = ("DistanceY" if perpendicular == "y" else "DistanceX") if diameter else (
            "DistanceX" if axis == "x" else "DistanceY")
        if diameter:
            format_spec = "⌀%.0f"
        else:
            format_spec = "%.0f"
        failures = []
        for _, _, _, first_name, second_name in candidates:
            if dim is not None:
                try:
                    page.removeView(dim)
                except Exception:
                    pass
                doc.removeObject(dim.Name)
                doc.recompute()
            refs = [(front, first_name), (front, second_name)]
            try:
                dim, measured = _dimension(
                    page, doc, descriptor, refs, kind, position, format_spec,
                    descriptor["value"], tolerance=tolerance,
                    measure_type="Projected")
                if target_midpoint is not None and hasattr(dim, "getLinearPoints"):
                    resolved = list(dim.getLinearPoints())
                    if len(resolved) >= 2:
                        coordinate = (lambda point: float(point.x)) if axis == "x" else (
                            lambda point: float(point.y))
                        resolved_midpoint = (coordinate(resolved[0]) +
                                             coordinate(resolved[1])) / 2.0
                        expected_midpoint = float(target_midpoint) * float(front.Scale)
                        midpoint_tolerance = max(0.2, abs(float(descriptor["value"]) *
                                                           float(front.Scale)) * 0.02)
                        if abs(resolved_midpoint - expected_midpoint) > midpoint_tolerance:
                            failures.append({
                                "vertices": [first_name, second_name],
                                "resolved_midpoint": resolved_midpoint,
                                "expected_midpoint": expected_midpoint,
                            })
                            try:
                                page.removeView(dim)
                            except Exception:
                                pass
                            doc.removeObject(dim.Name)
                            doc.recompute()
                            dim = None
                            continue
                return dim, measured
            except Exception as exc:
                dim = None
                failures.append({"vertices": [first_name, second_name], "error": str(exc)})
        raise RuntimeError("projected dimension search exhausted finite candidates: %s" %
                           failures[-4:])
    finally:
        preferences.SetBool("AutoCorrectRefs", previous)


def _projected_radius_dimension(page, doc, front, descriptor, position):
    """Associate R to a projected circular fillet edge in the main view."""
    preferences = _dimension_preferences()
    previous = bool(preferences.GetBool("AutoCorrectRefs", True))
    preferences.SetBool("AutoCorrectRefs", False)
    try:
        candidates = []
        target_local_x = float(position[0]) - float(front.X)
        target_local_y = float(position[1]) - float(front.Y)
        scale = float(front.Scale)
        for item in _selectable_edges(front):
            edge = item["edge"]
            radius = float(getattr(getattr(edge, "Curve", None), "Radius", 0.0))
            if radius <= 0.0:
                continue
            model_radius = radius
            try:
                center_x = (float(edge.BoundBox.XMin) + float(edge.BoundBox.XMax)) / 2.0
                center_y = (float(edge.BoundBox.YMin) + float(edge.BoundBox.YMax)) / 2.0
                location_error = math.hypot(center_x * scale - target_local_x,
                                            center_y * scale - target_local_y)
                page_anchor = (float(front.X) + center_x * scale,
                               float(front.Y) + center_y * scale)
            except Exception:
                location_error = float("inf")
                page_anchor = None
            candidates.append((abs(model_radius - float(descriptor["value"])),
                               location_error, item["name"], model_radius,
                               page_anchor))
        allowed = max(0.05, float(descriptor["value"]) * 0.01)
        failures = []
        for error, _, edge_name, model_radius, page_anchor in sorted(candidates)[:24]:
            if error > allowed:
                break
            try:
                # Place the text beside the exact projected edge selected for
                # References2D.  Equal-radius fillets can occur on opposite
                # shoulders, so a recipe-level X position is insufficient and
                # can produce a leader through the whole part.
                local_position = position
                if page_anchor is not None:
                    horizontal = -13.0 if page_anchor[0] >= float(front.X) else 13.0
                    local_position = (page_anchor[0] + horizontal,
                                      max(float(position[1]), page_anchor[1] + 11.0))
                result = _dimension(
                    page, doc, descriptor, [(front, edge_name)], "Radius", local_position,
                    "R%.2f", descriptor["value"], measure_type="Projected")
                dim = result[0]
                leader_length = (math.hypot(local_position[0] - page_anchor[0],
                                            local_position[1] - page_anchor[1])
                                 if page_anchor is not None else float("inf"))
                dim.addProperty("App::PropertyLength", "AICADLeaderLength", "AI CAD")
                dim.AICADLeaderLength = leader_length
                if hasattr(dim, "AngleOverride"):
                    dim.AngleOverride = True
                if hasattr(dim, "LineAngle"):
                    dim.LineAngle = 0.0
                doc.recompute()
                _yield_gui(250)
                return result[0], result[1], local_position
            except Exception as exc:
                failures.append({"edge": edge_name, "radius": model_radius,
                                 "error": str(exc)})
        raise RuntimeError("projected radius search failed: %s" % failures[-4:])
    finally:
        preferences.SetBool("AutoCorrectRefs", previous)


def _projected_chamfer_dimension(page, doc, front, descriptor, position):
    preferences = App.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/TechDraw/Dimensions")
    previous = bool(preferences.GetBool("AutoCorrectRefs", True))
    preferences.SetBool("AutoCorrectRefs", False)
    try:
        return _projected_chamfer_dimension_without_autocorrect(
            page, doc, front, descriptor, position)
    finally:
        preferences.SetBool("AutoCorrectRefs", previous)


def _projected_chamfer_dimension_without_autocorrect(page, doc, front, descriptor, position):
    """Create C-size from a stable, straight projected chamfer edge."""
    dim = doc.addObject("TechDraw::DrawViewDimension", safe_name("Dim_" + descriptor["role"],
                                                                 "Dimension"))
    dim.Label = descriptor["text"] + " — associative"
    page.addView(dim)
    dim.X = float(position[0]) - float(front.X)
    dim.Y = float(position[1]) - float(front.Y)
    dim.MeasureType = "Projected"
    dim.FormatSpec = "C%.0f"
    doc.recompute()
    _yield_gui(250)

    candidates = []
    for item in _selectable_edges(front):
        edge = item["edge"]
        curve = getattr(edge, "Curve", None)
        curve_type = str(getattr(curve, "TypeId", type(curve).__name__))
        if hasattr(curve, "Radius") or "Circle" in curve_type or "Arc" in curve_type:
            continue
        vertices = list(getattr(edge, "Vertexes", []))
        if len(vertices) != 2:
            continue
        delta = vertices[1].Point.sub(vertices[0].Point)
        dx, dy = abs(float(delta.x)), abs(float(delta.y))
        if dx <= 0.01 or dy <= 0.01:
            continue
        if abs(dx - descriptor["value"]) <= abs(dy - descriptor["value"]):
            candidates.append((abs(dx - descriptor["value"]), item["name"], "DistanceX"))
        else:
            candidates.append((abs(dy - descriptor["value"]), item["name"], "DistanceY"))

    failures = []
    allowed = max(0.05, abs(float(descriptor["value"])) * 0.005)
    for _, edge_name, kind in sorted(candidates)[:16]:
        dim.Type = kind
        dim.References2D = [(front, edge_name)]
        doc.recompute()
        _yield_gui(250)
        state = [str(item) for item in getattr(dim, "State", [])]
        if any("Invalid" in item or "Error" in item for item in state):
            failures.append({"edge": edge_name, "state": state})
            continue
        measured = _measure_from_references([(front, edge_name)], None, kind, "Projected")
        if abs(measured - float(descriptor["value"])) <= allowed:
            # Setting References2D can reset the format in FreeCAD 1.1.
            dim.FormatSpec = "C%.0f"
            doc.recompute()
            _yield_gui(250)
            return dim, measured
        failures.append({"edge": edge_name, "value": measured})

    try:
        page.removeView(dim)
    except Exception:
        pass
    doc.removeObject(dim.Name)
    doc.recompute()
    raise RuntimeError("C1 associative edge search failed after finite retries: %s" % failures[-4:])


def _primary_axis(shape):
    bbox = shape.BoundBox
    spans = [float(bbox.XLength), float(bbox.YLength), float(bbox.ZLength)]
    return max(range(3), key=lambda index: spans[index])


def _coordinate(point, axis):
    return (float(point.x), float(point.y), float(point.z))[axis]


def _true_vertex_pair(obj, expected):
    """Find a same-radial-coordinate vertex pair spanning the requested length."""
    vertices = list(obj.Shape.Vertexes)
    axis = _primary_axis(obj.Shape)
    candidates = []
    for first_index, first in enumerate(vertices, 1):
        for second_index, second in enumerate(vertices[first_index:], first_index + 1):
            delta = second.Point.sub(first.Point)
            axial = abs(_coordinate(delta, axis))
            perpendicular = math.sqrt(max(0.0, float(delta.Length) ** 2 - axial ** 2))
            error = abs(float(delta.Length) - float(expected))
            if error <= max(0.05, float(expected) * 0.005):
                candidates.append((perpendicular, error, first_index, second_index))
    if not candidates:
        raise RuntimeError("No true vertex pair measures %g on %s" % (expected, obj.Name))
    _, _, first_index, second_index = min(candidates)
    return [(obj, "Vertex%d" % first_index), (obj, "Vertex%d" % second_index)]


def _true_linear_edge(obj, expected):
    axis = _primary_axis(obj.Shape)
    candidates = []
    for edge_index, edge in enumerate(obj.Shape.Edges, 1):
        vertices = list(edge.Vertexes)
        if len(vertices) != 2:
            continue
        delta = vertices[1].Point.sub(vertices[0].Point)
        length = float(edge.Length)
        axial = abs(_coordinate(delta, axis))
        if abs(length - float(expected)) <= max(0.05, float(expected) * 0.005):
            candidates.append((abs(length - axial), edge_index))
    if not candidates:
        raise RuntimeError("No true linear edge measures %g on %s" % (expected, obj.Name))
    _, edge_index = min(candidates)
    return [(obj, "Edge%d" % edge_index)]


def _true_circle_edge(obj, expected_diameter):
    candidates = []
    for edge_index, edge in enumerate(obj.Shape.Edges, 1):
        curve = getattr(edge, "Curve", None)
        radius = float(getattr(curve, "Radius", 0.0))
        if radius > 0.0:
            candidates.append((abs(radius * 2.0 - float(expected_diameter)), edge_index))
    if not candidates or min(candidates)[0] > max(0.05, float(expected_diameter) * 0.005):
        raise RuntimeError("No true circular edge measures diameter %g on %s" %
                           (expected_diameter, obj.Name))
    _, edge_index = min(candidates)
    return [(obj, "Edge%d" % edge_index)]


def _projected_circle_dimension(page, doc, view, descriptor, position):
    candidates = []
    for item in _selectable_edges(view):
        radius = float(getattr(getattr(item["edge"], "Curve", None), "Radius", 0.0))
        if radius > 0.0:
            candidates.append((abs(radius * 2.0 - float(descriptor["value"])), item["name"]))
    if not candidates or min(candidates)[0] > max(0.05, float(descriptor["value"]) * 0.005):
        raise RuntimeError("No projected circle matches %s=%g" %
                           (descriptor["role"], descriptor["value"]))
    _, name = min(candidates)
    return _dimension(page, doc, descriptor, [(view, name)], "Diameter", position,
                      descriptor.get("format", "⌀%.0f"),
                      descriptor["value"])


def _circle_center(edge):
    curve = getattr(edge, "Curve", None)
    point = getattr(curve, "Center", None) or getattr(curve, "Location", None)
    if point is None:
        return None
    return float(point.x), float(point.y)


def _projected_circle_center_distance(page, doc, view, descriptor, position):
    circles = []
    feature_diameter = float(descriptor.get("feature_diameter") or 0.0)
    for item in _selectable_edges(view):
        radius = float(getattr(getattr(item["edge"], "Curve", None), "Radius", 0.0))
        center = _circle_center(item["edge"])
        if center is None or radius <= 0.0:
            continue
        if feature_diameter and abs(radius * 2.0 - feature_diameter) > max(0.05, feature_diameter * .005):
            continue
        circles.append((item["name"], center))
    trials = []
    for index, first in enumerate(circles):
        for second in circles[index + 1:]:
            dx = abs(second[1][0] - first[1][0])
            dy = abs(second[1][1] - first[1][1])
            for kind, value in (("DistanceX", dx), ("DistanceY", dy)):
                trials.append((abs(value - float(descriptor["value"])), kind,
                               first[0], second[0]))
    if not trials or min(trials)[0] > max(0.1, float(descriptor["value"]) * .01):
        raise RuntimeError("No opposite projected hole centers match PCD %g" % descriptor["value"])
    _, kind, first_name, second_name = min(trials)
    return _dimension(page, doc, descriptor,
                      [(view, first_name), (view, second_name)], kind, position,
                      "PCD ⌀%.0f", descriptor["value"])


def _projected_pitch_circle_dimension(page, doc, view, descriptor, position):
    """Create the conventional pitch circle, then dimension its diameter.

    A distance between two circular hole edges measures the tangent gap
    (PCD-hole diameter), not the hole-centre pitch.  The pitch circle is a
    legitimate construction entity derived from the current parametric hole
    pattern; a DrawViewDimension can then associate with that entity directly.
    """
    radius = float(descriptor["value"]) / 2.0
    black = (0.0, 0.0, 0.0, 0.0)
    tag = view.makeCosmeticCircle(App.Vector(0.0, 0.0, 0.0), radius,
                                  4, 0.18, black)
    if not tag:
        raise RuntimeError("TechDraw did not create the PCD construction circle")
    doc.recompute()
    Gui.updateGui()
    _yield_gui(250)
    derived = dict(descriptor)
    derived["format"] = "PCD ⌀%.0f"
    dim, measured = _projected_circle_dimension(
        page, doc, view, derived, position)
    dim.addProperty("App::PropertyString", "AICADAssociationSource", "AI CAD")
    dim.AICADAssociationSource = (
        "Pitch circle derived from current parametric bolt-hole sketch centres")
    return dim, measured


def _projected_linear_any_axis(page, doc, view, descriptor, position):
    points = _points(view)
    failures = []
    for axis, perpendicular in (("x", "y"), ("y", "x")):
        try:
            return _projected_vertex_dimension(
                page, doc, view, descriptor, position, axis, perpendicular)
        except Exception as exc:
            failures.append(str(exc))
    raise RuntimeError("No projected linear span matches %s: %s" %
                       (descriptor["role"], failures))


def _projected_center_from_edge(page, doc, view, descriptor, position, axis):
    points = _points(view)
    circles = []
    for item in _selectable_edges(view):
        center = _circle_center(item["edge"])
        radius = float(getattr(getattr(item["edge"], "Curve", None), "Radius", 0.0))
        if center is not None and radius > 0.0:
            circles.append((item["name"], center))
    coordinate = 0 if axis == "x" else 1
    trials = []
    for point in points:
        for circle_name, center in circles:
            value = abs(float(center[coordinate]) - float(point[axis]))
            trials.append((abs(value - float(descriptor["value"])), point["name"], circle_name))
    if not trials or min(trials)[0] > max(0.05, float(descriptor["value"]) * .01):
        raise RuntimeError("No hole center/base reference matches %s" % descriptor["role"])
    _, vertex_name, circle_name = min(trials)
    kind = "DistanceX" if axis == "x" else "DistanceY"
    return _dimension(page, doc, descriptor,
                      [(view, vertex_name), (view, circle_name)], kind, position,
                      "%.0f", descriptor["value"])


def _build_part_dimensions(doc, page, views, part_spec, descriptors, layout):
    if str(part_spec.get("part_type")) == "shaft":
        return _build_dimensions(doc, page, views["front"],
                                 _extract_model_spec(doc, views["front"].Source[0]),
                                 descriptors, layout)
    positions = {item["role"]: (item["x"], item["y"])
                 for item in layout["dimensions"]}
    created, measured_values, associative = [], {}, {}
    for descriptor in descriptors:
        view = views[descriptor.get("view", "front")]
        kind = descriptor.get("kind")
        if kind == "circle":
            dim, measured = _projected_circle_dimension(
                page, doc, view, descriptor, positions[descriptor["role"]])
        elif kind == "circle_centers":
            dim, measured = _projected_pitch_circle_dimension(
                page, doc, view, descriptor, positions[descriptor["role"]])
        elif kind == "center_from_edge_x":
            dim, measured = _projected_center_from_edge(
                page, doc, view, descriptor, positions[descriptor["role"]], "x")
        elif kind == "center_from_edge_y":
            dim, measured = _projected_center_from_edge(
                page, doc, view, descriptor, positions[descriptor["role"]], "y")
        else:
            dim, measured = _projected_linear_any_axis(
                page, doc, view, descriptor, positions[descriptor["role"]])
        created.append(dim)
        measured_values[descriptor["role"]] = measured
        associative[descriptor["role"]] = True
    return created, measured_values, associative


def _build_dimensions(doc, page, front, spec, descriptors, layout):
    points = _points(front)
    if len(points) < 4:
        raise RuntimeError("Front projection has insufficient vertices for dimensions")
    axis, perpendicular = _axis_info(points)
    low = min(item[axis] for item in points)
    high = max(item[axis] for item in points)
    scale = float(front.Scale)
    created = []
    measured_values = {}
    associative = {}
    positions = {item["role"]: (item["x"], item["y"])
                 for item in layout["dimensions"]}

    boundaries = [low]
    cursor = 0.0
    for segment in spec["segments"]:
        cursor += float(segment["length"])
        boundaries.append(low + cursor)
    overall = next(item for item in descriptors if item["role"] == "overall_length")
    dim, measured = _projected_vertex_dimension(
        page, doc, front, overall, positions[overall["role"]], axis, perpendicular,
        target_midpoint=(low + high) / 2.0, tolerance=overall.get("tolerance"))
    created.append(dim)
    measured_values[overall["role"]] = measured
    associative[overall["role"]] = True

    for descriptor in [item for item in descriptors if item["role"].startswith("shoulder_location")]:
        index = int(descriptor["boundary_index"])
        midpoint = (boundaries[0] + boundaries[index]) / 2.0
        dim, measured = _projected_vertex_dimension(
            page, doc, front, descriptor, positions[descriptor["role"]],
            axis, perpendicular, target_midpoint=midpoint)
        created.append(dim)
        measured_values[descriptor["role"]] = measured
        associative[descriptor["role"]] = True

    diameter_descriptors = [item for item in descriptors if item["role"].startswith("diameter")]
    for descriptor in diameter_descriptors:
        index = int(descriptor.get("segment_index", 0))
        midpoint = (boundaries[index] + boundaries[index + 1]) / 2.0
        dim, measured = _projected_vertex_dimension(
            page, doc, front, descriptor, positions[descriptor["role"]],
            axis, perpendicular, target_midpoint=midpoint,
            diameter=True, tolerance=None)
        created.append(dim)
        measured_values[descriptor["role"]] = measured
        associative[descriptor["role"]] = True

    chamfer = next((item for item in descriptors if item["role"] == "chamfer"), None)
    if chamfer:
        dim, measured = _projected_chamfer_dimension(
            page, doc, front, chamfer, positions[chamfer["role"]])
        created.append(dim)
        measured_values[chamfer["role"]] = measured
        associative[chamfer["role"]] = True

    radius = next((item for item in descriptors if item["role"] == "radius"), None)
    if radius:
        dim, measured, actual_position = _projected_radius_dimension(
            page, doc, front, radius, positions[radius["role"]])
        for item in layout["dimensions"]:
            if item["role"] != radius["role"]:
                continue
            dx = float(actual_position[0]) - float(item["x"])
            dy = float(actual_position[1]) - float(item["y"])
            item["x"], item["y"] = actual_position
            item["bbox"] = item["bbox"].moved(dx, dy)
            break
        created.append(dim)
        measured_values[radius["role"]] = measured
        associative[radius["role"]] = True
    return created, measured_values, associative


def _dimension_objects_for_page(page):
    """Enumerate page dimensions from the document dependency graph.

    DrawPage.Group is not a reliable Python container for DrawViewDimension in
    FreeCAD 1.1; using it made eight real dimensions look like zero and caused
    ``all([])`` to pass.  A dimension's InList reliably contains its page.
    """
    return [item for item in page.Document.Objects
            if getattr(item, "TypeId", "") == "TechDraw::DrawViewDimension"
            and page in list(getattr(item, "InList", []))]


def _sync_dimension_positions(dimensions, layout):
    positions = {item["role"]: (float(item["x"]), float(item["y"]))
                 for item in layout.get("dimensions") or []}
    for dim in dimensions:
        role = str(dim.Name).replace("Dim_", "", 1)
        if role not in positions:
            continue
        refs = list(getattr(dim, "References2D", []))
        reference_view = refs[0][0] if refs else None
        origin_x = float(getattr(reference_view, "X", 0.0))
        origin_y = float(getattr(reference_view, "Y", 0.0))
        dim.X = positions[role][0] - origin_x
        dim.Y = positions[role][1] - origin_y


def _reference_page_bounds(dim):
    references = list(getattr(dim, "References2D", []))
    reference_view = references[0][0] if references else None
    origin_x = float(getattr(reference_view, "X", 0.0))
    origin_y = float(getattr(reference_view, "Y", 0.0))
    coords = [(origin_x + float(dim.X), origin_y + float(dim.Y))]
    for reference in references:
        if not isinstance(reference, (tuple, list)) or len(reference) < 2:
            continue
        view = reference[0]
        names = reference[1]
        if isinstance(names, str):
            names = [names]
        for name in list(names or []):
            try:
                if str(name).startswith("Vertex"):
                    vertex = view.getVertexBySelection(str(name))
                    point = vertex.Point
                    scale = float(getattr(view, "Scale", 1.0))
                    coords.append((float(view.X) + float(point.x) * scale,
                                   float(view.Y) + float(point.y) * scale))
                elif str(name).startswith("Edge"):
                    edge = view.getEdgeBySelection(str(name))
                    box = edge.BoundBox
                    scale = float(getattr(view, "Scale", 1.0))
                    coords.extend([
                        (float(view.X) + float(box.XMin) * scale,
                         float(view.Y) + float(box.YMin) * scale),
                        (float(view.X) + float(box.XMax) * scale,
                         float(view.Y) + float(box.YMax) * scale),
                    ])
            except Exception as exc:
                raise RuntimeError("Cannot resolve %s reference %s: %s" %
                                   (dim.Name, name, exc))
    if len(coords) < 2:
        raise RuntimeError("Dimension %s has no resolved 2D geometry" % dim.Name)
    return Rect(min(item[0] for item in coords) - 1.5,
                min(item[1] for item in coords) - 1.5,
                max(item[0] for item in coords) + 1.5,
                max(item[1] for item in coords) + 1.5)


def _validate_actual_dimensions(page, layout, required_count):
    dimensions = _dimension_objects_for_page(page)
    safe = layout["safe_drawing_bounds"]
    if len(dimensions) != int(required_count):
        raise RuntimeError("Expected %d page dimensions, found %d" %
                           (required_count, len(dimensions)))
    bounds = {}
    failures = []
    for dim in dimensions:
        state = [str(item) for item in getattr(dim, "State", [])]
        refs = list(getattr(dim, "References2D", []))
        if not refs or bool(getattr(dim, "Arbitrary", False)):
            failures.append("%s is not associative" % dim.Name)
            continue
        if any("Invalid" in item or "Error" in item for item in state):
            failures.append("%s state=%s" % (dim.Name, state))
            continue
        if any("Touched" in item for item in state) or not any("Up-to-date" in item for item in state):
            failures.append("%s did not finish recomputing: %s" % (dim.Name, state))
            continue
        rect = _reference_page_bounds(dim)
        bounds[dim.Name] = rect.as_dict()
        if not safe.contains(rect):
            failures.append("%s leaves safe bounds: %s" % (dim.Name, rect.as_dict()))
    if failures:
        raise RuntimeError("Actual TechDraw dimension geometry validation failed: %s" % failures)
    return dimensions, bounds


def drawing_context(params, context):
    doc = current_document(context)
    body = next((obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"), None)
    if body is None or getattr(body, "Tip", None) is None:
        raise RuntimeError("Active document has no PartDesign Body Tip")
    source = body.Tip
    bbox = source.Shape.BoundBox
    model_spec = _extract_model_spec(doc, source)
    part_spec = _part_spec_from_model(doc, source, model_spec)
    return {"document": doc.Name, "label": doc.Label, "file_name": doc.FileName,
            "source": source.Name,
            "part_spec": part_spec,
            "bbox": {"x_length": float(bbox.XLength), "y_length": float(bbox.YLength),
                     "z_length": float(bbox.ZLength)}}


def create_techdraw(params, context):
    doc = current_document(context)
    source = _resolve(context, params.get("source"))
    finish_repair = _repair_shaft_finish_interference(doc, source)
    removed = _remove_managed_drawings(doc)
    spec = _extract_model_spec(doc, source)
    part_spec = _part_spec_from_model(doc, source, spec, params.get("part_spec"))
    feature_tree = [{"name": obj.Name, "label": obj.Label, "type_id": obj.TypeId}
                    for obj in doc.Objects]
    strategy = MechanicalDrawingRuleEngine().select_required_views(part_spec, feature_tree)
    descriptors = _part_dimension_descriptors(spec, part_spec, strategy)
    strategy_roles = set(strategy.get("dimensions") or [])
    if strategy_roles:
        descriptors = [item for item in descriptors if item["role"] in strategy_roles]
    if str(part_spec.get("part_type")) == "shaft" and spec["keyway_present"]:
        raise RuntimeError("Keyway exists but associative keyway width/depth/length references are unavailable")
    notes = [{"role": "manufacturing_notes", "text": "Material / surface / tolerance"}]
    layout_engine = DrawingLayoutEngine(max_iterations=8)
    layout = layout_engine.layout(spec["bbox"], descriptors, notes, strategy=strategy)

    page = doc.addObject("TechDraw::DrawPage", safe_name(params.get("name"), "DrawingPage"))
    page.Label = "AI CAD Copilot — Layout Validated Drawing"
    template = doc.addObject("TechDraw::DrawSVGTemplate", "DrawingTemplate")
    template.Template = _find_template(layout["page_format"])
    page.Template = template
    _set_template_fields(template, doc, source, params, layout)

    view_specs = {item["role"]: item for item in strategy["views"]}
    names = {"front": "FrontView", "end": "EndView", "side": "SideView",
             "section": "SectionView", "axonometric": "AxonometricView"}
    views = {}
    for role in layout["views"]:
        placement = layout["views"][role]
        view_spec = view_specs[role]
        view = doc.addObject("TechDraw::DrawViewPart", names.get(role, role.title() + "View"))
        view.Label = role.upper() + " — " + view_spec["reason"]
        page.addView(view)
        view.Source = [source]
        view.Direction = App.Vector(*view_spec["direction"])
        view.ScaleType = "Custom"
        view.Scale = float(placement["scale"])
        view.X, view.Y = float(placement["x"]), float(placement["y"])
        views[role] = view
    _wait_for_projection(doc, page, list(views.values()))
    # Centerlines depend on the projected Face0 geometry and therefore must be
    # created only after TechDraw has finished its first projection pass.
    for view_spec in strategy.get("views", []):
        role = view_spec.get("role")
        if role in views:
            _set_view_centerlines(views[role], view_spec.get("centerlines"))
    doc.recompute()
    Gui.updateGui()
    _yield_gui(250)
    actual_view_bounds = _fit_actual_projected_views(doc, views, layout)
    # Observe -> correct: the real projected bounds include curve/line padding
    # that cannot be known from the model bbox alone.  Re-run the same finite
    # collision solver before creating dimensions at their corrected positions.
    if not layout_engine._resolve(layout):
        raise RuntimeError("Dimension layout cannot clear actual projected view bounds")

    if str(part_spec.get("part_type")) == "shaft":
        dimensions, measured_values, associative = _build_dimensions(
            doc, page, views["front"], spec, descriptors, layout)
    else:
        dimensions, measured_values, associative = _build_part_dimensions(
            doc, page, views, part_spec, descriptors, layout)
    # Feature callouts can snap to the actual projected edge and thereby move
    # beyond their estimated text box.  Re-run the finite collision pass on
    # those observed positions, then apply the corrected coordinates back to
    # the real DrawViewDimension objects.
    if not layout_engine._resolve(layout):
        raise RuntimeError("Dimension layout cannot resolve post-association collisions")
    _sync_dimension_positions(dimensions, layout)
    note = doc.addObject("TechDraw::DrawViewAnnotation", "DrawingNote")
    page.addView(note)
    note.Text = [
        "DIMENSIONS IN mm",
        "Material: %s" % str(params.get("material") or "45钢"),
        "Surface finish: NOT SPECIFIED (no inferred requirement)",
        "Functional/general tolerances: only when sourced",
        "Projection: GB/T first-angle",
        "DO NOT SCALE",
        "Source: current Document",
    ]
    if hasattr(note, "TextSize"):
        note.TextSize = 2.5
    note.X = float(layout["notes_bounds"].center_x)
    note.Y = float(layout["notes_bounds"].top - 8.0)
    doc.recompute()
    for _ in range(6):
        for dimension in dimensions:
            try:
                dimension.recompute()
            except Exception:
                pass
        doc.recompute()
        Gui.updateGui()
        _yield_gui(250)

    actual_dimensions, actual_dimension_bounds = _validate_actual_dimensions(
        page, layout, len(descriptors))

    required = [item["role"] for item in descriptors]
    evidence = {
        "centerlines_present": _centerline_evidence(views, strategy),
        "line_types_valid": _centerline_format_evidence(views, strategy),
        "title_block_complete": bool(params.get("title") and params.get("material")),
        "drawing_standard_declared": True,
        "functional_tolerances_justified": strategy.get("functional_tolerances_justified", True),
    }
    validation = DrawingValidator().validate(layout, required, associative, evidence)
    actual_roles = {item.Name.replace("Dim_", "") for item in dimensions}
    if not set(required).issubset(actual_roles):
        validation["required_dimensions_present"] = False
        validation["passed"] = False
    if any(abs(float(value) - 0.63) < 0.005 for value in measured_values.values()):
        validation["spurious_0_63"] = True
        validation["passed"] = False
    else:
        validation["spurious_0_63"] = False
    validation["measured_values"] = measured_values
    validation["layout_iterations"] = layout["iterations"]
    validation["page_format"] = layout["page_format"]
    validation["scale"] = layout["scale_label"]
    validation["center_marks"] = evidence["centerlines_present"]
    validation["axis_centerline"] = evidence["centerlines_present"]
    validation["actual_view_bounds"] = actual_view_bounds
    validation["actual_dimension_bounds"] = actual_dimension_bounds
    validation["actual_dimension_count"] = len(actual_dimensions)
    expected_callouts = any(item["role"] in {"chamfer", "radius"}
                            for item in descriptors)
    feature_callouts = [item for item in actual_dimensions
                        if hasattr(item, "AICADLeaderLength")]
    validation["local_feature_callouts"] = bool(
        (not expected_callouts) or
        (feature_callouts and
         all(float(item.AICADLeaderLength) <= 25.0 for item in feature_callouts)))
    if not validation["local_feature_callouts"]:
        validation["passed"] = False
    validation["finish_interference_repair"] = finish_repair
    if not validation["inside_border"] or not validation["passed"]:
        raise RuntimeError("Drawing layout validation failed: %s" % validation)

    page.addProperty("App::PropertyBool", "AICADLayoutValidated", "AI CAD")
    page.addProperty("App::PropertyString", "AICADLayoutValidation", "AI CAD")
    page.addProperty("App::PropertyString", "AICADStandardScale", "AI CAD")
    page.AICADLayoutValidated = True
    page.AICADLayoutValidation = json.dumps(validation, ensure_ascii=False, sort_keys=True)
    page.AICADStandardScale = layout["scale_label"]
    for _ in range(6):
        for dimension in dimensions:
            try:
                dimension.recompute()
            except Exception:
                pass
        doc.recompute()
        Gui.updateGui()
        _yield_gui(250)
    context["drawing_page"] = page
    return {"page": page, "views": list(views.values()), "dimensions": dimensions,
            "template": template, "note": note, "measured_values": measured_values,
            "same_document_source": source.Name,
            "layout": DrawingLayoutEngine.serializable(layout),
            "layout_validation": validation, "removed_previous": removed,
            "finish_interference_repair": finish_repair}


def validate_techdraw(params, context):
    page = _resolve(context, params.get("page", "$drawing_page"))
    dimensions = _dimension_objects_for_page(page)
    for _ in range(6):
        for dimension in dimensions:
            try:
                dimension.recompute()
            except Exception:
                pass
        page.Document.recompute()
        Gui.updateGui()
        _yield_gui(250)
    if not bool(getattr(page, "AICADLayoutValidated", False)):
        raise RuntimeError("Drawing layout validated = FAIL")
    validation = json.loads(str(page.AICADLayoutValidation))
    if not validation.get("inside_border") or not validation.get("passed"):
        raise RuntimeError("Drawing layout validated = FAIL: %s" % validation)
    required_count = len(validation.get("required") or [])
    associative = (required_count > 0 and len(dimensions) == required_count and
                   all(bool(getattr(item, "References2D", [])) and
                       not bool(getattr(item, "Arbitrary", False)) and
                       not any("Invalid" in str(state) or "Error" in str(state)
                               for state in getattr(item, "State", []))
                       and any("Up-to-date" in str(state)
                               for state in getattr(item, "State", []))
                       and not any("Touched" in str(state)
                                   for state in getattr(item, "State", []))
                       for item in dimensions))
    validation["associative_dimensions"] = bool(associative)
    validation["passed"] = bool(validation["passed"] and associative)
    if not validation["passed"]:
        raise RuntimeError("Drawing layout validated = FAIL: %s" % validation)
    return {"page": page.Name, "drawing_layout_validated": "PASS",
            "validation": validation, "dimension_count": len(dimensions)}


def export_techdraw_pdf(params, context):
    page = _resolve(context, params.get("page", "$drawing_page"))
    if not bool(getattr(page, "AICADLayoutValidated", False)):
        raise RuntimeError("Refusing PDF export: Drawing layout validated != PASS")
    path = validate_output_path(params.get("path"), {".pdf"})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    page.Document.recompute()
    try:
        import TechDrawGui
        TechDrawGui.exportPageAsPdf(page, path)
    except Exception as first_error:
        try:
            page.ViewObject.saveAsPdf(path)
        except Exception as second_error:
            raise RuntimeError("TechDraw PDF export failed: %s; %s" %
                               (first_error, second_error))
    if not os.path.isfile(path) or os.path.getsize(path) < 1000:
        raise RuntimeError("TechDraw PDF was not created")
    return {"path": path, "page": page.Name,
            "drawing_layout_validated": "PASS"}
