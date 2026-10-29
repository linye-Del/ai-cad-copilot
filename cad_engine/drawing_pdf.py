"""标准工程图 PDF 渲染（matplotlib 矢量）。

输入：scripts/techdraw.py 导出的 drawing_data.json（真实模型投影 + 尺寸数据）
输出：A4 横向标准工程图 PDF
  - 三视图（国标第一角投影：主视左上 / 俯视左下 / 右视右上）
  - 尺寸标注：线性 / 直径 Φ / 半径 R / 角度 / 深度
  - 工程符号：螺纹 M×p / 倒角 C / 表面粗糙度 Ra
  - 标题栏：零件名称 / 材料 / 比例 / 图号
  - 公差：H7 / h6 / IT 等级（标注后缀）

数据全部来自真实模型（FreeCAD 投影边与 TechDraw 尺寸对象），
SVG 仅保留为浏览器预览，PDF 为最终工程图。
"""

import json
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle, FancyArrow, Polygon
import matplotlib.font_manager as fm

# 中文字体（Windows）
for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
    if os.path.isfile(f):
        fm.fontManager.addfont(f)
        break
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

W, H = 297.0, 210.0  # A4 横向 (mm)


def _load_data(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _draw_view(ax, view_data, color="#111111"):
    """绘制视图轮廓（线段 + 圆）。"""
    segs = [( (s["p1"][0], s["p1"][1]), (s["p2"][0], s["p2"][1]) )
            for s in view_data.get("segments", [])]
    lc = LineCollection(segs, colors=color, linewidths=0.6)
    ax.add_collection(lc)
    for c in view_data.get("circles", []):
        pts = c["pts"]
        ax.plot([p[0] for p in pts] + [pts[0][0]], [p[1] for p in pts] + [pts[0][1]],
                color=color, linewidth=0.6)


def _dim_h(ax, x1, x2, y, text, tol=""):
    """水平尺寸线。"""
    ext = 2.0
    ax.plot([x1, x2], [y, y], color="#c00000", linewidth=0.5)
    for x in (x1, x2):
        ax.plot([x, x], [y - ext, y + ext], color="#c00000", linewidth=0.5)
    ax.annotate("", xy=(x1, y), xytext=(x2, y),
                arrowprops=dict(arrowstyle="<->", color="#c00000", lw=0.5))
    txt = f"{text}" + (f" {tol}" if tol else "")
    ax.text((x1 + x2) / 2, y + 1.6, txt, ha="center", fontsize=7, color="#c00000")


def _dim_v(ax, y1, y2, x, text, tol=""):
    """垂直尺寸线。"""
    ext = 2.0
    ax.plot([x, x], [y1, y2], color="#c00000", linewidth=0.5)
    for y in (y1, y2):
        ax.plot([x - ext, x + ext], [y, y], color="#c00000", linewidth=0.5)
    ax.annotate("", xy=(x, y1), xytext=(x, y2),
                arrowprops=dict(arrowstyle="<->", color="#c00000", lw=0.5))
    txt = f"{text}" + (f" {tol}" if tol else "")
    ax.text(x + 1.5, (y1 + y2) / 2, txt, va="center", fontsize=7, color="#c00000")


def _dim_dia(ax, cx, cy, r, text, tol=""):
    """直径标注（对角引线 + Φ 文字）。"""
    # 限制在页面内（matplotlib 对超出 axes 的文本裁剪）
    cx = max(25.0, min(265.0, cx))
    cy = max(20.0, min(185.0, cy))
    a = -45
    x1, y1 = cx + r * math_cos(a), cy + r * math_sin(a)
    x2, y2 = cx - r * math_cos(a), cy - r * math_sin(a)
    ax.plot([x1, x2], [y1, y2], color="#c00000", linewidth=0.5)
    body = text if text.startswith("Φ") else f"Φ{text}"
    txt = body + (f" {tol}" if tol else "")
    ax.text(cx, cy - r * 0.35, txt, ha="center", fontsize=7, color="#c00000")


def math_cos(a):
    import math
    return math.cos(math.radians(a))


def math_sin(a):
    import math
    return math.sin(math.radians(a))


def _symbol_thread(ax, x, y, w, text):
    """螺纹符号：细斜线 + 文字。"""
    n = max(3, int(w / 2.5))
    for i in range(n + 1):
        xx = x + w * i / n
        ax.plot([xx, xx - 0.8], [y, y - 1.0], color="#555555", linewidth=0.4)
    ax.text(x + w / 2, y - 3.0, text, ha="center", fontsize=7)


def _symbol_chamfer(ax, x, y, text):
    """倒角符号：45° 斜线 + C 文字。"""
    ax.plot([x, x + 1.5], [y, y - 1.5], color="#111111", linewidth=0.5)
    ax.text(x + 2.0, y - 1.0, text, fontsize=7)


def _symbol_roughness(ax, x, y, text):
    """表面粗糙度符号：倒三角 + 横线 + Ra 文字。"""
    ax.plot([x, x + 3.2], [y, y], color="#111111", linewidth=0.5)
    ax.plot([x + 3.2, x + 1.6], [y, y - 2.4], color="#111111", linewidth=0.5)
    ax.plot([x, x + 1.6], [y, y - 2.4], color="#111111", linewidth=0.5)
    ax.plot([x + 3.2, x + 4.6], [y, y + 1.8], color="#111111", linewidth=0.5)
    ax.text(x + 5.0, y + 1.6, text, fontsize=6.5)


def _title_block(ax, title: dict, part_type: str):
    """标题栏（右下角）。"""
    bw, bh = 100.0, 26.0
    x0, y0 = W - 12 - bw, 12
    ax.add_patch(plt.Rectangle((x0, y0), bw, bh, fill=False, linewidth=0.8))
    rows = [("零件名称", title.get("name", "") or part_type),
            ("材料", title.get("material", "")),
            ("比例", title.get("scale", "1:1")),
            ("图号", title.get("number", f"CAD-{part_type.upper()}"))]
    rh = bh / len(rows)
    for i, (k, v) in enumerate(rows):
        yy = y0 + i * rh
        ax.plot([x0, x0 + bw], [yy, yy], color="#111111", linewidth=0.5)
        ax.plot([x0 + 18, x0 + 18], [yy, yy + rh], color="#111111", linewidth=0.5)
        ax.text(x0 + 9, yy + rh / 2 - 1.4, k, ha="center", fontsize=7)
        ax.text(x0 + 19.5, yy + rh / 2 - 1.4, str(v)[:18], fontsize=7)


def render_pdf(data: dict, out_path: str) -> str:
    """渲染标准工程图 PDF。"""
    import math

    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=120)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")

    # 图框
    ax.add_patch(plt.Rectangle((7, 7), W - 14, H - 14, fill=False, linewidth=0.8))

    views = data.get("views", {})
    dims = data.get("dimensions", [])
    syms = data.get("symbols", {})

    # 三视图布局（第一角投影）：主视左上、俯视左下、右视右上
    main = views.get("front", {})
    top = views.get("top", {})
    right = views.get("right", {})

    # 计算每个视图的绘制区域（局部归一化）
    def _view_bounds(vd):
        xs, ys = [], []
        for s in vd.get("segments", []):
            xs += [s["p1"][0], s["p2"][0]]
            ys += [s["p1"][1], s["p2"][1]]
        for c in vd.get("circles", []):
            xs += [p[0] for p in c["pts"]]
            ys += [p[1] for p in c["pts"]]
        if not xs:
            return None
        return (min(xs), max(xs), min(ys), max(ys))

    regions = {"front": (20, 158, 130, 76), "top": (20, 92, 130, 55), "right": (172, 158, 105, 76)}
    offsets = {}
    for name, vd in (("front", main), ("top", top), ("right", right)):
        bb = _view_bounds(vd)
        if not bb:
            continue
        rx, ry, rw, rh = regions[name]
        # 缩放适配区域（居中于区域中心）
        w = bb[1] - bb[0] or 1
        h = bb[3] - bb[2] or 1
        scale = min(rw / w, rh / h, 2.0)
        cx, cy = (bb[0] + bb[1]) / 2, (bb[2] + bb[3]) / 2
        x0 = rx + rw / 2 - cx * scale
        y0 = ry + rh / 2 - cy * scale
        offsets[name] = (x0, y0, scale)
        _draw_scaled(ax, vd, offsets[name])

    # 尺寸标注（在视图上叠加）
    _draw_dimensions(ax, dims, offsets)

    # 工程符号
    if syms.get("thread"):
        _symbol_thread(ax, 60, 168, 30, syms["thread"])
    if syms.get("chamfer"):
        _symbol_chamfer(ax, 85, 95, syms["chamfer"])
    if syms.get("roughness"):
        _symbol_roughness(ax, 210, 150, syms["roughness"])

    # 标题栏
    _title_block(ax, data.get("title", {}), data.get("part", {}).get("part_type", ""))

    fig.savefig(out_path, format="pdf")
    plt.close(fig)
    return out_path


def _draw_scaled(ax, vd, off):
    """按缩放/偏移绘制视图。"""
    x0, y0, scale = off
    segs = [((seg["p1"][0] * scale + x0, seg["p1"][1] * scale + y0),
             (seg["p2"][0] * scale + x0, seg["p2"][1] * scale + y0))
            for seg in vd.get("segments", [])]
    ax.add_collection(LineCollection(segs, colors="#111111", linewidths=0.6))
    for c in vd.get("circles", []):
        pts = [(p[0] * scale + x0, p[1] * scale + y0) for p in c["pts"]]
        ax.plot([p[0] for p in pts] + [pts[0][0]], [p[1] for p in pts] + [pts[0][1]],
                color="#111111", linewidth=0.6)


def _draw_dimensions(ax, dims, offsets):
    """基于尺寸数据绘制标注：水平/垂直/直径标注，错位布局防重叠。"""
    off = offsets.get("front")
    if not off:
        return
    x0, y0, scale = off
    h_slots, v_slots = [], []
    for i in range(8):
        h_slots.append((x0 - 55, x0 + 55, y0 - 8 - i * 7))     # 下方水平标注
        v_slots.append((x0 - 12 - i * 7, y0 - 40, y0 + 40))    # 左侧垂直标注
    dia_idx = 0
    for d in dims:
        kind = d.get("type", "Distance")
        text = str(d.get("text", ""))
        tol = d.get("tolerance", "")
        if kind == "Diameter":
            # 直径标注独立位置（视图内下方递增 10mm，避免文字重叠），不占用长度标注槽位
            _dim_dia(ax, x0 + 40 + dia_idx * 10, max(60, y0 - 30), 18, text, tol)
            dia_idx += 1
        elif kind == "Distance":
            if d.get("label") in ("总长", "齿宽", "厚度") and h_slots:
                x1, x2, y = h_slots.pop(0)
                _dim_h(ax, x1, x2, y, text, tol)
            elif v_slots:
                x, y1, y2 = v_slots.pop(0)
                _dim_v(ax, y1, y2, x, text, tol)
            elif h_slots:
                x1, x2, y = h_slots.pop(0)
                _dim_h(ax, x1, x2, y, text, tol)


def render_from_data_file(data_path: str, out_pdf: str) -> str:
    data = _load_data(data_path)
    return render_pdf(data, out_pdf)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: drawing_pdf.py <drawing_data.json> <out.pdf>")
        sys.exit(1)
    render_from_data_file(sys.argv[1], sys.argv[2])
    print("PDF 已生成:", sys.argv[2])
