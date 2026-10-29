"""程序化 SVG 工程图生成器（示意级，国标第一角投影）。

替代 FreeCAD DXF 导出（1.1.3 中 importDXF.export 概率性进程崩溃）。
纯 Python 实现，输入零件 spec，输出 A4 横向（297x210mm）SVG：
三视图 + 关键尺寸标注 + 标题栏。

用法:
    from cad_engine import drawing_svg
    svg = drawing_svg.render(spec)          # 返回 SVG 字符串
    drawing_svg.render(spec, "drawing.svg") # 写入文件
"""

import datetime
import math
from html import escape

# 画布：A4 横向，单位 mm
W, H = 297.0, 210.0
MARGIN = 12.0

STYLE = {
    "line": "stroke:#111;stroke-width:0.35;fill:none",
    "hidden": "stroke:#111;stroke-width:0.35;fill:none;stroke-dasharray:3,1.5",
    "center": "stroke:#555;stroke-width:0.25;fill:none;stroke-dasharray:8,2,1.5,2",
    "thread": "stroke:#111;stroke-width:0.3;fill:none",
    "dim": "stroke:#c00;stroke-width:0.3;fill:none",
    "dim_text": "fill:#c00;font-size:4.5px;font-family:SimSun,serif",
    "text": "fill:#111;font-size:4.5px;font-family:SimSun,serif",
    "title": "fill:#111;font-size:5px;font-family:SimSun,serif;font-weight:bold",
    "border": "stroke:#111;stroke-width:0.5;fill:none",
}


def _svg_open():
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}mm" height="{H}mm" style="background:#fff">')


def _line(x1, y1, x2, y2, style="line"):
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" style="{STYLE[style]}"/>'


def _polyline(pts, style="line", close=False):
    p = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    if close:
        p += f" {pts[0][0]:.2f},{pts[0][1]:.2f}"
    return f'<polyline points="{p}" style="{STYLE[style]}"/>'


def _circle(cx, cy, r, style="line", dashed=False):
    return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" style="{STYLE[style]}"/>'


def _text(x, y, s, style="text", anchor="middle"):
    return f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" style="{STYLE[style]}">{escape(str(s))}</text>'


def _dim_h(x1, x2, y, label, ext=2.2, gap=2.0):
    """水平尺寸线 + 延伸线。"""
    out = []
    for x in (x1, x2):
        out.append(_line(x, y - ext, x, y + ext, "dim"))
    out.append(_line(x1, y, x2, y, "dim"))
    out.append(_line(x1, y, x1 - 0.8, y, "dim"))
    out.append(_line(x2, y, x2 + 0.8, y, "dim"))
    mid = (x1 + x2) / 2
    out.append(_text(mid, y - 1.0, label, "dim_text"))
    return "".join(out)


def _dim_v(y1, y2, x, label, ext=2.2):
    """垂直尺寸线 + 延伸线。"""
    out = []
    for y in (y1, y2):
        out.append(_line(x - ext, y, x + ext, y, "dim"))
    out.append(_line(x, y1, x, y2, "dim"))
    out.append(_line(x, y1, x + 0.8, y1 + 0.8, "dim"))
    out.append(_line(x, y2, x - 0.8, y2 - 0.8, "dim"))
    mid = (y1 + y2) / 2
    out.append(_text(x + 1.0, mid, label, "dim_text", anchor="start"))
    return "".join(out)


def _dim_dia(cx, cy, r, label, angle=-45):
    a = math.radians(angle)
    x1, y1 = cx + r * math.cos(a), cy + r * math.sin(a)
    x2, y2 = cx + r * math.cos(a + math.pi), cy + r * math.sin(a + math.pi)
    out = [_line(x1, y1, x2, y2, "dim")]
    out.append(_line(x1, y1, x1 - 1.2 * math.cos(a), y1 - 1.2 * math.sin(a), "dim"))
    out.append(_line(x2, y2, x2 + 1.2 * math.cos(a), y2 + 1.2 * math.sin(a), "dim"))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    out.append(_text(mx, my - 1.0, label, "dim_text"))
    return "".join(out)


# ---------- 各零件三视图 ----------

def _bolt_views(origin, params):
    """螺栓：主视图（水平）+ 左视图（六角头）。origin=(x,y) 为主视图头部起点。"""
    d = float(params.get("d", 10))
    L = float(params.get("L", 40))
    b = float(params.get("b", 2 * d + 6))
    s = float(params.get("s", 1.5 * d))
    k = float(params.get("k", 0.65 * d))
    ox, oy = origin
    scale = 2.0  # 局部放大

    out = [_text(ox + (L * scale) / 2, oy - 10, "主视图 (正面)", "title")]

    # 螺栓轴水平放置：头部在左
    hh, hw = k * scale, s * scale           # 头部高/宽
    shank_y = hh / 2 - (d * scale) / 2      # 螺杆上沿
    x0 = ox + hw
    x_shank_end = x0 + L * scale
    x_thread_end = x_shank_end - b * scale

    # 头部（正六边形轮廓简化：矩形 + 顶部倒角斜线）
    out.append(_polyline([(ox, oy), (ox, oy + hh), (ox + hw, oy + hh), (ox + hw, oy)], close=True))
    out.append(_line(ox + 1.2, oy + hh * 0.15, ox + hw - 1.2, oy + hh * 0.15, "hidden"))
    # 中心线
    out.append(_line(ox - 6, oy + hh / 2, x_shank_end + 6, oy + hh / 2, "center"))
    # 螺杆
    out.append(_line(x0, oy + shank_y, x_shank_end, oy + shank_y))
    out.append(_line(x0, oy + hh - shank_y, x_shank_end, oy + hh - shank_y))
    # 螺纹段（细斜线示意，全螺纹时整段）
    n_lines = max(3, int(b * scale / 2.5))
    for i in range(n_lines + 1):
        xx = x_thread_end + (x_shank_end - x_thread_end) * i / n_lines
        out.append(_line(xx, oy + shank_y + 0.8, xx - 0.8, oy + hh - shank_y - 0.8, "thread"))
    # 杆端面
    out.append(_line(x_shank_end, oy + shank_y, x_shank_end, oy + hh - shank_y))
    # 头部端面倒角
    out.append(_line(ox, oy + 1.0, ox + 1.0, oy, "hidden"))
    out.append(_line(ox, oy + hh - 1.0, ox + 1.0, oy + hh, "hidden"))

    # 尺寸：总长 L、螺纹 b、杆径 d、头高 k、对边 s
    out.append(_dim_h(ox, x_shank_end, oy + hh + 5.0, f"L={L:g}"))
    out.append(_dim_h(x_thread_end, x_shank_end, oy - 4.0, f"b={b:g}"))
    out.append(_dim_v(oy + shank_y, oy + hh - shank_y, x_shank_end + 3.5, f"d={d:g}"))
    out.append(_dim_v(oy, oy + hh, ox - 3.0, f"k={k:g}"))
    out.append(_dim_h(ox, ox + hw, oy - 4.0, f"s={s:g}"))

    # 左视图：六角头（正六边形外接圆 R=s/√3）
    lx, ly = x_shank_end + 22, oy + hh / 2
    out.append(_text(lx, ly - 14, "左视图", "title"))
    R = s / math.sqrt(3.0)
    hex_pts = [(lx + R * math.cos(math.radians(30 + 60 * i)), ly + R * math.sin(math.radians(30 + 60 * i))) for i in range(6)]
    out.append(_polyline(hex_pts, close=True))
    out.append(_circle(lx, ly, R, "center"))
    out.append(_circle(lx, ly, (d / 2) * scale * 0.9, "hidden"))
    out.append(_dim_dia(lx, ly, R, f"S={s:g}", angle=-135))
    return "".join(out)


def _shaft_views(origin, params):
    """阶梯轴：主视图（沿中心线多段矩形）+ 左视图（最大段圆）。"""
    segs = params.get("segments") or []
    if not segs:
        return ""
    ox, oy = origin
    scale = 1.4
    dmax = max(float(s["d"]) for s in segs)
    total = sum(float(s["L"]) for s in segs)
    cx = oy + dmax * scale / 2  # 中心线

    out = [_text(ox + total * scale / 2, oy - 10, "主视图 (正面)", "title")]
    x = ox
    for i, s in enumerate(segs):
        d, L = float(s["d"]), float(s["L"])
        w = L * scale
        h = d * scale
        y_top = cx - h / 2
        out.append(_line(x, y_top, x + w, y_top))
        out.append(_line(x, cx + h / 2, x + w, cx + h / 2))
        out.append(_line(x, y_top, x, cx + h / 2))
        out.append(_line(x + w, y_top, x + w, cx + h / 2))
        x += w
    out.append(_line(ox - 8, cx, x + 8, cx, "center"))
    # 端部倒角示意
    out.append(_line(ox, cx + dmax * scale * 0.45, ox + 1.5, cx + dmax * scale * 0.45 - 1.5, "hidden"))

    # 尺寸：各段 L、直径、总长
    x = ox
    for i, s in enumerate(segs):
        d, L = float(s["d"]), float(s["L"])
        out.append(_dim_h(x, x + L * scale, oy + dmax * scale + 5.0, f"L{i+1}={L:g}"))
        out.append(_dim_v(cx - d * scale / 2, cx + d * scale / 2, x + 2.5, f"d{i+1}={d:g}"))
        x += L * scale
    out.append(_dim_h(ox, x, oy + dmax * scale + 10.0, f"总长={total:g}"))

    # 左视图：最大直径圆
    lx = x + 18
    ly = cx
    out.append(_text(lx, ly - dmax * scale / 2 - 4, "左视图", "title"))
    out.append(_circle(lx, ly, dmax * scale / 2))
    out.append(_circle(lx, ly, 2.0, "center"))
    out.append(_line(lx - dmax * scale / 2 - 1, ly, lx + dmax * scale / 2 + 1, ly, "center"))
    out.append(_line(lx, ly - dmax * scale / 2 - 1, lx, ly + dmax * scale / 2 + 1, "center"))
    out.append(_dim_dia(lx, ly, dmax * scale / 2, f"d={dmax:g}", angle=-135))
    return "".join(out)


def _flange_views(origin, params):
    """法兰：主视图（端面圆+孔分布）+ 侧视图（矩形轮廓）。"""
    D = float(params.get("D", 160))
    d = float(params.get("d", 50))
    t = float(params.get("t", 18))
    n = int(params.get("n", 8))
    pcd = float(params.get("pcd", (D + d) / 2))
    hole_d = float(params.get("hole_d", 11))
    scale = 1.1
    ox, oy = origin
    R = D * scale / 2
    cx, cy = ox + R, oy + R
    r = R * 2.6

    out = [_text(cx, oy - 8, "主视图 (端面)", "title")]
    out.append(_circle(cx, cy, R))
    out.append(_circle(cx, cy, d * scale / 2, "hidden"))
    out.append(_circle(cx, cy, pcd * scale / 2, "center"))
    out.append(_line(cx - R - 2, cy, cx + R + 2, cy, "center"))
    out.append(_line(cx, cy - R - 2, cx, cy + R + 2, "center"))
    for i in range(n):
        a = math.radians(360.0 * i / n)
        hx, hy = cx + pcd * scale / 2 * math.cos(a), cy + pcd * scale / 2 * math.sin(a)
        out.append(_circle(hx, hy, hole_d * scale / 2, style="line"))
    out.append(_dim_dia(cx, cy, R, f"D={D:g}", angle=-135))
    out.append(_dim_dia(cx, cy, d * scale / 2, f"d={d:g}", angle=-45))
    out.append(_text(cx, cy + R + 3.5, f"{n}-M{round(hole_d-1):g} 均布 PCD={pcd:g}", "text"))

    # 侧视图：矩形 t x D
    sx = cx + r + 8
    sy = cy - R
    sh = D * scale * 0.62
    out.append(_text(sx + t * scale / 2, sy - 8, "侧视图", "title"))
    out.append(_polyline([(sx, sy), (sx + t * scale, sy), (sx + t * scale, sy + sh), (sx, sy + sh)], close=True))
    out.append(_line(sx, sy + sh / 2, sx + t * scale, sy + sh / 2, "center"))
    out.append(_dim_h(sx, sx + t * scale, sy + sh + 3.5, f"t={t:g}"))
    out.append(_dim_v(sy, sy + sh, sx - 3.0, f"D={D:g}"))
    return "".join(out)


def _gear_views(origin, params):
    """齿轮：主视图（齿顶圆/分度圆/齿根圆+毂孔+键槽）+ 侧视图（矩形）。"""
    m = float(params.get("m", 2.5))
    z = int(params.get("z", 20))
    b = float(params.get("b", 25))
    x = float(params.get("x", 0))
    d_hub = float(params.get("d_hub", 30))
    da = m * z + 2 * m * (1 + x)
    df = m * z - 2.5 * m + 2 * m * x
    scale = 0.9
    ox, oy = origin
    R = da * scale / 2
    cx, cy = ox + R, oy + R
    r = R * 2.6

    out = [_text(cx, oy - 8, "主视图 (端面)", "title")]
    out.append(_circle(cx, cy, R))
    out.append(_circle(cx, cy, m * z * scale / 2, "center"))
    out.append(_circle(cx, cy, df * scale / 2, "hidden"))
    out.append(_circle(cx, cy, d_hub * scale / 2))
    out.append(_line(cx - R - 2, cy, cx + R + 2, cy, "center"))
    out.append(_line(cx, cy - R - 2, cx, cy + R + 2, "center"))
    # 键槽示意（毂孔内上部）
    kw = 8 * scale / 2
    out.append(_polyline([(cx - kw / 2, cy - d_hub * scale / 2),
                          (cx - kw / 2, cy - d_hub * scale / 2 - 3.2 * scale),
                          (cx + kw / 2, cy - d_hub * scale / 2 - 3.2 * scale),
                          (cx + kw / 2, cy - d_hub * scale / 2)]))
    out.append(_dim_dia(cx, cy, R, f"da={da:g}", angle=-135))
    out.append(_dim_dia(cx, cy, d_hub * scale / 2, f"d_hub={d_hub:g}", angle=-45))
    out.append(_text(cx, cy + R + 3.5, f"m={m:g}  z={z}  分度圆 d={m*z:g}  df={df:g}", "text"))

    # 侧视图：矩形 b x da
    sx = cx + r + 8
    sy = cy - R
    sh = da * scale * 0.62
    out.append(_text(sx + b * scale / 2, sy - 8, "侧视图", "title"))
    out.append(_polyline([(sx, sy), (sx + b * scale, sy), (sx + b * scale, sy + sh), (sx, sy + sh)], close=True))
    out.append(_line(sx, sy + sh / 2, sx + b * scale, sy + sh / 2, "center"))
    out.append(_dim_h(sx, sx + b * scale, sy + sh + 3.5, f"b={b:g}"))
    out.append(_dim_v(sy, sy + sh, sx - 3.0, f"da={da:g}"))
    return "".join(out)


_VIEWS = {
    "bolt": _bolt_views,
    "shaft": _shaft_views,
    "flange": _flange_views,
    "gear": _gear_views,
}


def _title_block(spec):
    """标题栏（右下角，约 90x26mm）。"""
    ptype = spec.get("part_type", "")
    params = spec.get("params", {})
    name = spec.get("part_name") or ptype
    material = str(params.get("material", ""))
    standard = {"bolt": "GB/T 5782-2016", "shaft": "GB/T 4678", "flange": "GB/T 9116",
                "gear": "GB/T 1357"}.get(ptype, "")
    x0, y0 = W - 100, H - 30
    cw, ch = 34, 6
    out = []
    rows = [("零件名称", name), ("材料", material), ("标准", standard),
            ("比例", "1:1"), ("图号", f"CAD-{ptype.upper()}"), ("日期", datetime.date.today().strftime("%Y-%m-%d"))]
    for i, (k, v) in enumerate(rows):
        y = y0 + i * ch
        out.append(_line(x0, y, x0 + cw, y, "border"))
        out.append(_line(x0, y + ch, x0 + cw, y + ch, "border"))
        out.append(_line(x0 + 12, y, x0 + 12, y + ch, "border"))
        out.append(_text(x0 + 6, y + 4.4, k, "title", anchor="middle"))
        out.append(_text(x0 + 13.5, y + 4.4, v, "text", anchor="start"))
    out.append(_line(x0, y0, x0, y0 + len(rows) * ch, "border"))
    out.append(_line(x0 + cw, y0, x0 + cw, y0 + len(rows) * ch, "border"))
    return "".join(out)


def _border():
    return (_line(MARGIN - 5, MARGIN - 5, W - MARGIN + 5, MARGIN - 5, "border")
            + _line(W - MARGIN + 5, MARGIN - 5, W - MARGIN + 5, H - MARGIN + 5, "border")
            + _line(W - MARGIN + 5, H - MARGIN + 5, MARGIN - 5, H - MARGIN + 5, "border")
            + _line(MARGIN - 5, H - MARGIN + 5, MARGIN - 5, MARGIN - 5, "border"))


def render(spec: dict) -> str:
    """生成工程图 SVG 字符串。"""
    ptype = spec.get("part_type", "")
    fn = _VIEWS.get(ptype)
    if not fn:
        raise ValueError(f"不支持的零件类型: {ptype}")
    parts = [_svg_open(), _border()]
    parts.append(fn((MARGIN + 4, MARGIN + 10), spec.get("params", {})))
    parts.append(_title_block(spec))
    parts.append("</svg>")
    return "".join(parts)


def render_file(spec: dict, path: str):
    """生成工程图 SVG 并写入文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(spec))
    return path


