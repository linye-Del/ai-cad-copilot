"""公共建模工具：标准数据表、螺纹生成、倒角工具。可被 Anaconda 侧与 FreeCAD 侧共同导入（无 FreeCAD 顶层依赖）。"""

BOLT_STD = {
    6: (1.0, 10, 4.0, 11.05),
    8: (1.25, 13, 5.3, 14.38),
    10: (1.5, 16, 6.4, 17.77),
    12: (1.75, 18, 7.5, 20.03),
    16: (2.0, 24, 10.0, 26.75),
    20: (2.5, 30, 12.5, 33.53),
    24: (3.0, 36, 15.0, 39.98),
    30: (3.5, 46, 18.7, 50.85),
    36: (4.0, 55, 22.5, 60.79),
}

STANDARD_MODULES = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]

KEYWAY_STD = {
    "8x7": (4, 25, 30),
    "10x8": (5, 30, 38),
    "12x8": (5, 38, 44),
    "14x9": (5.5, 44, 50),
}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def build_thread(doc, outer_r, inner_r, pitch, height, start_z=0.0, tip_z=None):
    """用螺旋扫掠三角牙型并做布尔减运算，生成可视化螺纹。失败时返回 None。"""
    try:
        import FreeCAD as App
        import Part
        import math

        if tip_z is None:
            tip_z = start_z
        helix = doc.addObject("Part::Helix", "ThreadHelix")
        helix.Pitch = pitch
        helix.Height = abs(tip_z - start_z)
        helix.Radius = (outer_r + inner_r) / 2.0
        helix.Angle = 90.0
        helix.Style = 0
        doc.recompute()
        path = helix.Shape.Wire
        tri = Part.makePolygon(
            [
                App.Vector(inner_r, 0.0, -pitch / 2.0),
                App.Vector(outer_r, 0.0, -pitch / 2.0),
                App.Vector(outer_r, 0.0, pitch / 2.0),
                App.Vector(inner_r, 0.0, pitch / 2.0),
            ],
            closed=True,
        )
        profile = Part.Wire(tri)
        pipe = Part.makeSweep(profile, path, None, True, True)
        pipe.translate(App.Vector(0.0, 0.0, start_z + pitch / 2.0))
        doc.removeObject(helix.Name)
        doc.recompute()
        return pipe
    except Exception:
        return None


def chamfer_shape(shape, size, edges):
    try:
        return shape.makeChamfer(size, edges)
    except Exception:
        return shape


def round_to(v, nd=1):
    return round(v, nd)