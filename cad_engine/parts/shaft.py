"""阶梯轴（多段圆柱轴，可带键槽与段间圆角）。"""

from base import chamfer_shape

META = {
    "key": "shaft",
    "name": "阶梯轴",
    "name_en": "Stepped Shaft",
    "standard": "自定设计 / GB/T 1095 键槽",
    "fields": [
        {
            "name": "segments",
            "label": "轴段（直径×长度）",
            "unit": "mm",
            "type": "list",
            "item_fields": [
                {"name": "d", "label": "直径", "unit": "mm", "type": "number"},
                {"name": "L", "label": "长度", "unit": "mm", "type": "number"},
            ],
            "required": True,
            "help": "例如 25×60、30×40、35×50",
        },
        {"name": "chamfer", "label": "端部倒角", "unit": "mm", "type": "number", "required": False, "default": 1.0},
        {"name": "fillet", "label": "段间圆角", "unit": "mm", "type": "number", "required": False, "default": 0.0},
        {
            "name": "keyway",
            "label": "键槽",
            "unit": "",
            "type": "group",
            "required": False,
            "fields": [
                {"name": "enabled", "label": "启用键槽", "type": "bool", "default": False},
                {"name": "seg_index", "label": "所在轴段(0起)", "type": "number", "default": 0},
                {"name": "w", "label": "键宽", "unit": "mm", "type": "number", "default": 8},
                {"name": "t", "label": "键槽深", "unit": "mm", "type": "number", "default": 4},
                {"name": "lk", "label": "键槽长", "unit": "mm", "type": "number", "default": 40},
            ],
        },
        {"name": "material", "label": "材料", "unit": "", "type": "text", "required": False, "default": "45钢"},
    ],
    "examples": [
        "设计一根阶梯轴：三段直径25、30、35mm，长度60、40、50mm，端部倒角C1，材料45钢",
        "阶梯轴 30×80 + 40×60，末端C2倒角，第0段加键槽8×4×50",
    ],
}


def derive(p):
    segs = p.get("segments") or []
    cleaned = []
    for s in segs:
        d = float(s.get("d", 0))
        L = float(s.get("L", 0))
        if d > 0 and L > 0:
            cleaned.append({"d": d, "L": L})
    p["segments"] = cleaned
    p.setdefault("chamfer", 1.0)
    p.setdefault("fillet", 0.0)
    p.setdefault("material", "45钢")
    kw = p.get("keyway") or {}
    if kw.get("enabled") and cleaned:
        idx = int(kw.get("seg_index", 0))
        idx = min(max(idx, 0), len(cleaned) - 1)
        kw["seg_index"] = idx
        kw.setdefault("w", 8)
        kw.setdefault("t", 4)
        kw.setdefault("lk", min(cleaned[idx]["L"], 40.0))
        p["keyway"] = kw
    else:
        p["keyway"] = None
    return p


def build(doc, p):
    import FreeCAD as App
    import Part

    segs = p["segments"]
    z = 0.0
    starts = []
    bodies = []
    for s in segs:
        starts.append(z)
        bodies.append(Part.makeCylinder(s["d"] / 2.0, s["L"], App.Vector(0, 0, z), App.Vector(0, 0, 1)))
        z += s["L"]

    body = bodies[0]
    for b in bodies[1:]:
        body = body.fuse(b)

    total = z
    cham = float(p.get("chamfer", 1.0))
    if cham > 0:
        end_edges = [
            e
            for e in body.Edges
            if e.Vertexes
            and (
                min(v.Z for v in e.Vertexes) > total - 0.01
                or max(v.Z for v in e.Vertexes) < 0.01
            )
        ]
        body = chamfer_shape(body, cham, end_edges)

    fillet = float(p.get("fillet", 0.0))
    if fillet > 0 and len(segs) > 1:
        junc = starts[1:]
        f_edges = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and any(abs(e.Curve.Center.z - zj) < 0.02 for zj in junc)
            and abs(e.Length - 2 * 3.141592653589793 * e.Curve.Radius) < 1e-3
        ]
        try:
            body = body.makeFillet(fillet, f_edges)
        except Exception:
            pass

    kw = p.get("keyway")
    if kw:
        idx = int(kw["seg_index"])
        w = float(kw["w"])
        dep = float(kw["t"])
        lk = float(kw["lk"])
        seg = segs[idx]
        r = seg["d"] / 2.0
        box = Part.makeBox(w, dep, lk)
        box.translate(App.Vector(-w / 2.0, r - dep, starts[idx]))
        body = body.cut(box)

    feat = doc.addObject("Part::Feature", "Part")
    feat.Label = "Shaft"
    feat.Shape = body
    return feat