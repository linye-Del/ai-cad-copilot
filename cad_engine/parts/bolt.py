"""六角头螺栓（GB/T 5782-2016）。"""

from base import BOLT_STD, build_thread, chamfer_shape, clamp

META = {
    "key": "bolt",
    "name": "六角头螺栓",
    "name_en": "Hex Head Bolt",
    "standard": "GB/T 5782-2016",
    "fields": [
        {"name": "d", "label": "公称直径", "unit": "mm", "type": "number", "required": True, "help": "M6~M48 常用系列"},
        {"name": "L", "label": "螺栓长度", "unit": "mm", "type": "number", "required": True},
        {"name": "b", "label": "螺纹长度", "unit": "mm", "type": "number", "required": False, "help": "留空自动按标准 b=2d+6"},
        {"name": "pitch", "label": "螺距", "unit": "mm", "type": "number", "required": False, "help": "留空按标准粗牙"},
        {"name": "grade", "label": "性能等级", "unit": "", "type": "text", "required": False, "default": "8.8"},
        {"name": "material", "label": "材料", "unit": "", "type": "text", "required": False, "default": "40Cr"},
        {"name": "surface", "label": "表面处理", "unit": "", "type": "text", "required": False, "default": "发黑处理"},
    ],
    "examples": [
        "生成一个M10×40的六角头螺栓，8.8级，螺纹长度25mm，材料40Cr，表面发黑",
        "M16×70 六角头螺栓，A级，全螺纹",
    ],
}


def derive(p):
    d = float(p.get("d", 10))
    L = float(p.get("L", 40))
    std = BOLT_STD.get(round(d), BOLT_STD[10])
    pitch, s, k, e = std
    p["s"] = s
    p["k"] = k
    p["e"] = e
    p.setdefault("pitch", pitch)
    b_std = 2 * d + 6
    if p.get("b") is None:
        p["b"] = round(min(b_std, L), 1)
    p["b"] = clamp(float(p["b"]), 0.5, L)
    p.setdefault("grade", "8.8")
    p.setdefault("material", "40Cr")
    p.setdefault("surface", "发黑处理")
    return p


def build(doc, p):
    import math

    import FreeCAD as App
    import Part

    d = float(p["d"])
    L = float(p["L"])
    pitch = float(p["pitch"])
    s = float(p["s"])
    k = float(p["k"])
    b = float(p["b"])
    R = s / math.sqrt(3.0)
    c = round(clamp(0.06 * d, 0.3, 1.2), 2)

    pts = [
        App.Vector(R * math.cos(math.radians(30 + 60 * i)), R * math.sin(math.radians(30 + 60 * i)), 0.0)
        for i in range(6)
    ]
    head = Part.Face(Part.Wire(Part.makePolygon(pts, True))).extrude(App.Vector(0, 0, k))
    top_edges = [
        e for e in head.Edges if e.Vertexes and min(v.Z for v in e.Vertexes) > k - 0.01
    ]
    head = chamfer_shape(head, c, top_edges)

    shank = Part.makeCylinder(d / 2.0, L, App.Vector(0, 0, k), App.Vector(0, 0, 1))
    body = head.fuse(shank)
    tip_edges = [
        e
        for e in body.Edges
        if e.Vertexes and min(v.Z for v in e.Vertexes) > k + L - 0.01
    ]
    body = chamfer_shape(body, c, tip_edges)

    thread_start = k + L - b
    pipe = build_thread(doc, d / 2.0, d / 2.0 - 0.5415 * pitch, pitch, b, thread_start, k + L)
    if pipe is not None:
        body = body.cut(pipe)

    feat = doc.addObject("Part::Feature", "Part")
    feat.Label = "Bolt"
    feat.Shape = body
    return feat