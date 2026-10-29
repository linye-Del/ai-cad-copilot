"""直齿圆柱齿轮（渐开线齿廓，支持变位，GB/T 1357 模数系列）。"""

import math

from base import STANDARD_MODULES

META = {
    "key": "gear",
    "name": "直齿圆柱齿轮",
    "name_en": "Spur Gear",
    "standard": "GB/T 1357 模数系列",
    "fields": [
        {"name": "m", "label": "模数", "unit": "mm", "type": "number", "required": True, "help": "标准系列 1~10"},
        {"name": "z", "label": "齿数", "unit": "齿", "type": "number", "required": True},
        {"name": "b", "label": "齿宽", "unit": "mm", "type": "number", "required": True},
        {"name": "alpha", "label": "压力角", "unit": "°", "type": "number", "required": False, "default": 20.0},
        {"name": "x", "label": "变位系数", "unit": "", "type": "number", "required": False, "default": 0.0},
        {"name": "d_hub", "label": "孔径", "unit": "mm", "type": "number", "required": True},
        {"name": "precision", "label": "精度等级", "unit": "级", "type": "number", "required": False, "default": 8},
        {"name": "material", "label": "材料", "unit": "", "type": "text", "required": False, "default": "45钢 调质"},
    ],
    "examples": [
        "生成直齿圆柱齿轮：模数2.5，齿数20，齿宽25mm，压力角20度，孔径30mm，8级精度",
        "齿轮 m=3 z=30 齿宽40 孔径35",
    ],
}


def involute_polar(rb, r):
    if r <= rb:
        return 0.0
    t = math.sqrt((r / rb) ** 2 - 1.0)
    return t - math.atan(t)


def derive(p):
    m = float(p.get("m", 2.5))
    z = int(p.get("z", 20))
    alpha = float(p.get("alpha", 20.0))
    x = float(p.get("x", 0.0))
    b = float(p.get("b", 25.0))
    d = m * z
    da = d + 2.0 * m * (1.0 + x)
    df = d - 2.5 * m + 2.0 * m * x
    db = d * math.cos(math.radians(alpha))
    p.setdefault("alpha", alpha)
    p.setdefault("x", x)
    p.setdefault("precision", 8)
    p.setdefault("material", "45钢 调质")
    p["derived"] = {
        "d": round(d, 2),
        "da": round(da, 2),
        "df": round(df, 2),
        "db": round(db, 2),
        "m_in_std": round(m, 2) in STANDARD_MODULES,
    }
    return p


def _tooth_profile_points(p):
    import FreeCAD as App

    m = float(p["m"])
    z = int(p["z"])
    alpha = float(p.get("alpha", 20.0))
    x = float(p.get("x", 0.0))
    d = m * z
    da = d + 2.0 * m * (1.0 + x)
    df = d - 2.5 * m + 2.0 * m * x
    db = d * math.cos(math.radians(alpha))
    rb = db / 2.0

    half_w = math.pi / z
    thick_half = math.pi / (2.0 * z)
    rot = thick_half - involute_polar(rb, d / 2.0)
    r0 = max(df / 2.0, rb)
    a = rot + involute_polar(rb, r0)
    b_ang = rot + involute_polar(rb, da / 2.0)

    npts = 24
    pts = []
    if df / 2.0 < rb:
        pts.append(App.Vector(df / 2.0 * math.cos(-a), df / 2.0 * math.sin(-a), 0))
    for i in range(npts + 1):
        r = r0 + (da / 2.0 - r0) * i / npts
        ang = -(rot + involute_polar(rb, r))
        pts.append(App.Vector(r * math.cos(ang), r * math.sin(ang), 0))
    for i in range(npts + 1):
        ang = -b_ang + (2.0 * b_ang) * i / npts
        r = da / 2.0
        pts.append(App.Vector(r * math.cos(ang), r * math.sin(ang), 0))
    for i in range(npts + 1):
        r = da / 2.0 - (da / 2.0 - r0) * i / npts
        ang = rot + involute_polar(rb, r)
        pts.append(App.Vector(r * math.cos(ang), r * math.sin(ang), 0))
    if df / 2.0 < rb:
        pts.append(App.Vector(df / 2.0 * math.cos(a), df / 2.0 * math.sin(a), 0))
    return pts


def _full_ring_wire(p):
    import FreeCAD as App
    import Part

    z = int(p["z"])
    m = float(p["m"])
    x = float(p.get("x", 0.0))
    df = m * z - 2.5 * m + 2.0 * m * x
    step = 2.0 * math.pi / z
    a = _tooth_profile_points(p)[0]
    a = math.atan2(a.y, a.x)
    pts = _tooth_profile_points(p)
    ring = []
    for k in range(z):
        off = step * k
        for pt in pts:
            ang = math.atan2(pt.y, pt.x) + off
            r = math.hypot(pt.x, pt.y)
            ring.append(App.Vector(r * math.cos(ang), r * math.sin(ang), 0))
        ang0 = a + off
        ang1 = a + off + step - 2.0 * a
        n = 16
        for i in range(1, n + 1):
            ang = ang0 + (ang1 - ang0) * i / n
            ring.append(App.Vector(df / 2.0 * math.cos(ang), df / 2.0 * math.sin(ang), 0))
    return Part.Wire(Part.makePolygon(ring, True))


def build(doc, p):
    import FreeCAD as App
    import Part

    b = float(p["b"])
    body = Part.Face(_full_ring_wire(p)).extrude(App.Vector(0, 0, b))

    d_hub = float(p["d_hub"])
    if d_hub > 0:
        bore = Part.makeCylinder(d_hub / 2.0, b + 2.0, App.Vector(0, 0, -1), App.Vector(0, 0, 1))
        body = body.cut(bore)

    feat = doc.addObject("Part::Feature", "Part")
    feat.Label = "Gear"
    feat.Shape = body
    return feat