"""法兰盘（圆形法兰，含螺栓孔与可选凸面密封面）。"""

from base import chamfer_shape, clamp

META = {
    "key": "flange",
    "name": "法兰盘",
    "name_en": "Flange Plate",
    "standard": "自定设计 / GB/T 9112 参考",
    "fields": [
        {"name": "D", "label": "外径", "unit": "mm", "type": "number", "required": True},
        {"name": "d", "label": "内径", "unit": "mm", "type": "number", "required": True},
        {"name": "t", "label": "厚度", "unit": "mm", "type": "number", "required": True},
        {"name": "n", "label": "螺栓孔数", "unit": "个", "type": "number", "required": False, "default": 8},
        {"name": "pcd", "label": "分度圆直径", "unit": "mm", "type": "number", "required": False, "help": "螺栓孔中心圆，留空自动"},
        {"name": "hole_d", "label": "螺栓孔径", "unit": "mm", "type": "number", "required": False, "default": 11.0},
        {"name": "chamfer", "label": "外缘倒角", "unit": "mm", "type": "number", "required": False, "default": 2.0},
        {"name": "rf_d", "label": "凸台直径(0=平面)", "unit": "mm", "type": "number", "required": False, "default": 0.0},
        {"name": "rf_h", "label": "凸台高度", "unit": "mm", "type": "number", "required": False, "default": 2.0},
        {"name": "material", "label": "材料", "unit": "", "type": "text", "required": False, "default": "Q235B"},
    ],
    "examples": [
        "设计一个法兰盘：外径160mm，内径50mm，厚度18mm，8个M10螺栓孔，分度圆直径130mm",
        "法兰 外径200 内径80 厚20，4孔，孔径13，凸台直径120高3",
    ],
}


def derive(p):
    D = float(p.get("D", 160))
    d = float(p.get("d", 50))
    if p.get("pcd") is None:
        p["pcd"] = round((D + d) / 2.0, 1)
    if p.get("n") is None:
        p["n"] = 4 if D < 120 else 8
    p["n"] = int(p.get("n", 8))
    p.setdefault("hole_d", 11.0)
    p.setdefault("chamfer", 2.0)
    p.setdefault("rf_d", 0.0)
    p.setdefault("rf_h", 2.0)
    p.setdefault("material", "Q235B")
    p["pcd"] = clamp(float(p["pcd"]), float(d) + float(p["hole_d"]), float(D) - float(p["hole_d"]) - 2)
    return p


def build(doc, p):
    import math

    import FreeCAD as App
    import Part

    D = float(p["D"])
    d = float(p["d"])
    t = float(p["t"])
    n = int(p["n"])
    pcd = float(p["pcd"])
    hole_d = float(p["hole_d"])
    cham = float(p.get("chamfer", 2.0))

    body = Part.makeCylinder(D / 2.0, t, App.Vector(0, 0, 0), App.Vector(0, 0, 1))
    bore = Part.makeCylinder(d / 2.0, t + 2.0, App.Vector(0, 0, -1), App.Vector(0, 0, 1))
    body = body.cut(bore)
    for i in range(n):
        ang = 2.0 * math.pi * i / n
        hole = Part.makeCylinder(hole_d / 2.0, t + 2.0, App.Vector(0, 0, -1), App.Vector(0, 0, 1))
        hole.translate(App.Vector(pcd / 2.0 * math.cos(ang), pcd / 2.0 * math.sin(ang), 0))
        body = body.cut(hole)

    if cham > 0:
        ring = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - D / 2.0) < 0.5
            and (abs(e.Curve.Center.z - 0) < 0.02 or abs(e.Curve.Center.z - t) < 0.02)
        ]
        body = chamfer_shape(body, min(cham, t / 3.0), ring)

    rf_d = float(p.get("rf_d", 0.0))
    if rf_d > 0 and rf_d < D:
        rf_h = float(p.get("rf_h", 2.0))
        rf = Part.makeCylinder(rf_d / 2.0, rf_h, App.Vector(0, 0, t), App.Vector(0, 0, 1))
        rf = rf.cut(Part.makeCylinder(d / 2.0, rf_h + 1, App.Vector(0, 0, t - 0.5), App.Vector(0, 0, 1)))
        body = body.fuse(rf)

    feat = doc.addObject("Part::Feature", "Part")
    feat.Label = "Flange"
    feat.Shape = body
    return feat