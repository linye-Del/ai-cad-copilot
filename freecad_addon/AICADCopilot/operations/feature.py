"""Native PartDesign feature operations."""

import FreeCAD as App

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


def _body_for(context, params):
    return _resolve(context, params.get("body", "$body"))


def _validate_feature(feature, name):
    if hasattr(feature, "Shape") and feature.Shape.isNull():
        raise RuntimeError("%s produced an empty shape" % name)
    if getattr(feature, "State", None) and "Invalid" in str(feature.State):
        raise RuntimeError("%s is invalid: %s" % (name, feature.State))


def create_pad(params, context):
    doc = current_document(context)
    body = _body_for(context, params)
    profile = _resolve(context, params.get("profile"))
    name = safe_name(params.get("name"), "Pad")
    pad = body.newObject("PartDesign::Pad", name)
    pad.Label = str(params.get("label") or name)[:128]
    pad.Profile = profile
    pad.Length = float(params["length"])
    if params.get("midplane"):
        pad.Midplane = True
    pad.Reversed = bool(params.get("reversed", False))
    doc.recompute()
    _validate_feature(pad, name)
    return pad


def create_revolution(params, context):
    doc = current_document(context)
    body = _body_for(context, params)
    profile = _resolve(context, params.get("profile"))
    name = safe_name(params.get("name"), "Revolution")
    revolution = body.newObject("PartDesign::Revolution", name)
    revolution.Label = str(params.get("label") or name)[:128]
    revolution.Profile = profile
    axis = str(params.get("axis", "V_Axis"))
    revolution.ReferenceAxis = (profile, [axis])
    revolution.Angle = float(params.get("angle", 360.0))
    revolution.Reversed = bool(params.get("reversed", False))
    doc.recompute()
    _validate_feature(revolution, name)
    return revolution


def create_pocket(params, context):
    doc = current_document(context)
    body = _body_for(context, params)
    prior_tip = getattr(body, "Tip", None)
    prior_volume = float(prior_tip.Shape.Volume) if (
        prior_tip is not None and hasattr(prior_tip, "Shape") and
        not prior_tip.Shape.isNull()
    ) else 0.0
    profile = _resolve(context, params.get("profile"))
    name = safe_name(params.get("name"), "Pocket")
    pocket = body.newObject("PartDesign::Pocket", name)
    pocket.Label = str(params.get("label") or name)[:128]
    pocket.Profile = profile
    pocket.Length = float(params["length"])
    if params.get("midplane"):
        pocket.Midplane = True
    pocket.Reversed = bool(params.get("reversed", False))
    doc.recompute()
    _validate_feature(pocket, name)
    result_volume = float(pocket.Shape.Volume)
    tolerance = max(1e-6, prior_volume * 1e-9)
    if prior_volume > 0.0 and result_volume >= prior_volume - tolerance:
        raise RuntimeError(
            "%s did not remove material (before=%g, after=%g); "
            "check sketch placement and pocket direction" %
            (name, prior_volume, result_volume)
        )
    return pocket


def create_additive_helix(params, context):
    """Create a native PartDesign additive helix from a constrained profile."""
    doc = current_document(context)
    body = _body_for(context, params)
    profile = _resolve(context, params.get("profile"))
    name = safe_name(params.get("name"), "AdditiveHelix")
    helix = body.newObject("PartDesign::AdditiveHelix", name)
    helix.Label = str(params.get("label") or name)[:128]
    helix.Profile = profile
    helix.ReferenceAxis = (profile, [str(params.get("axis", "V_Axis"))])
    helix.Mode = 0
    helix.Pitch = float(params["pitch"])
    helix.Height = float(params["height"])
    helix.Angle = float(params.get("angle", 0.0))
    helix.Growth = float(params.get("growth", 0.0))
    helix.LeftHanded = bool(params.get("left_handed", False))
    helix.Reversed = bool(params.get("reversed", False))
    doc.recompute()
    _validate_feature(helix, name)
    return helix


def _edge_names(shape, selector):
    kind = str((selector or {}).get("kind", "terminal_circular_edges"))
    tolerance = float((selector or {}).get("tolerance", 0.05))
    terminal_clearance = float((selector or {}).get("terminal_clearance", 2.0))
    z_min = shape.BoundBox.ZMin
    z_max = shape.BoundBox.ZMax
    names = []
    for index, edge in enumerate(shape.Edges, 1):
        try:
            if edge.Curve.TypeId != "Part::GeomCircle":
                continue
            z = edge.CenterOfMass.z
        except Exception:
            continue
        terminal = abs(z - z_min) <= tolerance or abs(z - z_max) <= tolerance
        if kind == "terminal_circular_edges" and terminal:
            names.append("Edge%d" % index)
        elif (kind == "shoulder_circular_edges" and not terminal and
              min(abs(z - z_min), abs(z - z_max)) > terminal_clearance):
            names.append("Edge%d" % index)
    if kind == "all_edges":
        names = ["Edge%d" % i for i in range(1, len(shape.Edges) + 1)]
    if not names:
        raise RuntimeError("No edges matched selector %s" % kind)
    return names


def create_chamfer(params, context):
    doc = current_document(context)
    body = _body_for(context, params)
    base = _resolve(context, params.get("base"))
    name = safe_name(params.get("name"), "Chamfer")
    edges = _edge_names(base.Shape, params.get("selector"))
    chamfer = body.newObject("PartDesign::Chamfer", name)
    chamfer.Label = str(params.get("label") or name)[:128]
    chamfer.Base = (base, edges)
    chamfer.Size = float(params.get("size", 1.0))
    doc.recompute()
    _validate_feature(chamfer, name)
    return chamfer


def create_fillet(params, context):
    doc = current_document(context)
    body = _body_for(context, params)
    base = _resolve(context, params.get("base"))
    name = safe_name(params.get("name"), "Fillet")
    edges = _edge_names(base.Shape, params.get("selector", {"kind": "shoulder_circular_edges"}))
    fillet = body.newObject("PartDesign::Fillet", name)
    fillet.Label = str(params.get("label") or name)[:128]
    fillet.Base = (base, edges)
    fillet.Radius = float(params.get("radius", 1.0))
    doc.recompute()
    _validate_feature(fillet, name)
    return fillet


def create_linear_pattern(params, context):
    """Create a native PartDesign linear pattern from one or more features."""
    doc = current_document(context)
    body = _body_for(context, params)
    originals = params.get("originals") or [params.get("original")]
    originals = [_resolve(context, item) for item in originals if item]
    if not originals:
        raise ValueError("Linear pattern requires at least one original feature")
    name = safe_name(params.get("name"), "LinearPattern")
    pattern = body.newObject("PartDesign::LinearPattern", name)
    pattern.Label = str(params.get("label") or name)[:128]
    pattern.Originals = originals
    axis_name = str(params.get("axis") or "Z_Axis")
    axis = next((item for item in body.Origin.OriginFeatures
                 if item.Name == axis_name or item.Label == axis_name), None)
    if axis is None:
        raise ValueError("Unknown Body pattern axis: %s" % axis_name)
    pattern.Direction = (axis, [""])
    pattern.Length = float(params["length"])
    pattern.Occurrences = int(params.get("occurrences", 2))
    pattern.Reversed = bool(params.get("reversed", False))
    doc.recompute()
    _validate_feature(pattern, name)
    return pattern


def create_hole(params, context):
    """Create a native PartDesign Hole driven by a sketch containing hole centers."""
    doc = current_document(context)
    body = _body_for(context, params)
    profile = _resolve(context, params.get("profile"))
    name = safe_name(params.get("name"), "Hole")
    hole = body.newObject("PartDesign::Hole", name)
    hole.Label = str(params.get("label") or name)[:128]
    hole.Profile = profile
    if hasattr(hole, "Diameter"):
        hole.Diameter = float(params["diameter"])
    if hasattr(hole, "Depth"):
        hole.Depth = float(params.get("depth", 10.0))
    if hasattr(hole, "DepthType") and params.get("through_all"):
        # FreeCAD exposes enum ordering differently between releases; the
        # string assignment is stable where supported, integer fallback is 1.
        try:
            hole.DepthType = "Through all"
        except Exception:
            hole.DepthType = 1
    doc.recompute()
    _validate_feature(hole, name)
    return hole


def remove_fillet_preserve_downstream(params, context):
    """Remove a Fillet and rebuild a following Pocket on the Fillet base.

    FreeCAD's PartDesign chain makes a later Pocket depend on the previous Tip.
    Blind ``removeObject`` therefore corrupts the history. This operation keeps
    the keyway sketch, recreates the Pocket after the Chamfer, and rewires any
    TechDraw views to the rebuilt current Tip.
    """
    doc = current_document(context)
    fillet = _resolve(context, params.get("name") or "Fillet")
    if fillet.TypeId != "PartDesign::Fillet":
        raise ValueError("Object '%s' is not a PartDesign Fillet" % fillet.Name)
    body = getattr(fillet, "_Body", None)
    if body is None:
        body = next((item for item in fillet.InList if item.TypeId == "PartDesign::Body"), None)
    if body is None:
        raise RuntimeError("Fillet is not inside a PartDesign Body")
    base = fillet.Base[0] if isinstance(fillet.Base, tuple) else fillet.Base
    fillet_name = fillet.Name
    base_name = base.Name
    downstream = [item for item in doc.Objects
                  if item.TypeId == "PartDesign::Pocket"
                  and getattr(item, "BaseFeature", None) == fillet]
    if len(downstream) > 1:
        raise RuntimeError("More than one downstream Pocket depends on the Fillet")
    pocket_data = None
    old_pocket = downstream[0] if downstream else None
    if old_pocket is not None:
        pocket_data = {
            "name": old_pocket.Name, "label": old_pocket.Label,
            "profile": old_pocket.Profile[0] if isinstance(old_pocket.Profile, tuple) else old_pocket.Profile,
            "length": float(old_pocket.Length), "midplane": bool(old_pocket.Midplane),
            "reversed": bool(old_pocket.Reversed),
        }
    drawing_views = [item for item in doc.Objects if item.TypeId == "TechDraw::DrawViewPart"
                     and fillet in list(getattr(item, "Source", []))]
    if old_pocket is not None:
        doc.removeObject(old_pocket.Name)
    body.Tip = base
    for view in drawing_views:
        view.Source = [base]
    doc.removeObject(fillet.Name)
    doc.recompute()
    rebuilt = None
    if pocket_data:
        rebuilt = body.newObject("PartDesign::Pocket", pocket_data["name"])
        rebuilt.Label = pocket_data["label"]
        rebuilt.Profile = pocket_data["profile"]
        rebuilt.Length = pocket_data["length"]
        rebuilt.Midplane = pocket_data["midplane"]
        rebuilt.Reversed = pocket_data["reversed"]
        doc.recompute()
        _validate_feature(rebuilt, rebuilt.Name)
        for view in drawing_views:
            view.Source = [rebuilt]
        body.Tip = rebuilt
    doc.recompute()
    return {"removed": fillet_name, "base": base_name,
            "rebuilt_pocket": rebuilt.Name if rebuilt else "",
            "rewired_views": [view.Name for view in drawing_views]}
