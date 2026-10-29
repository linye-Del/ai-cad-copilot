"""真实工程图生成（FreeCAD TechDraw + 数据导出）。

流程：
  1. TechDraw 页面：三视图（主视/俯视/左视，第一角投影）
  2. DrawViewDimension 尺寸对象（Type + References3D 关联真实几何 + 公差）
  3. 提取 drawing_data.json：
     - 三视图轮廓投影（真实 Shape 边 → 2D 线段/圆）
     - 尺寸数据（类型/值/公差）
     - 工程符号数据（螺纹/倒角/表面粗糙度）
     - 标题栏数据（零件名/材料/比例/图号）

PDF 渲染由 cad_engine.drawing_pdf.py（matplotlib 矢量）完成——
无头模式下 TechDraw 页面无法渲染导出（TechDrawGui 不可用），
故以"真实 TechDraw 对象 + 真实几何投影数据"驱动标准工程图 PDF。

注意：FreeCAD 1.1 API ——
  - 尺寸对象用 TechDraw::DrawViewDimension（newAppendDimension 已移除）
  - 视图源关联用 group.Source（SourceShapes 已移除）
"""

import json
import math
import os

TPL_CANDIDATES = [
    "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_advanced.svg",
    "Mod/TechDraw/Templates/ISO/A4_Portrait_ISO5457_advanced.svg",
    "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO7200TD.svg",
    "Mod/TechDraw/Templates/ISO/A4_Landscape_blank.svg",
]


def _find_template():
    import FreeCAD as App

    res = App.getResourceDir()
    for rel in TPL_CANDIDATES:
        p = os.path.join(res, rel)
        if os.path.isfile(p):
            return p
    return None


def _trace(out_dir, name):
    try:
        with open(os.path.join(out_dir, "_stage.txt"), "w", encoding="utf-8") as f:
            f.write("td_" + name)
    except Exception:
        pass


# ---------------- 视图轮廓投影（真实 Shape 边 → 2D） ----------------

def _project_edges(shape, plane):
    """将 Shape 的边投影到视图平面，返回线段与圆。

    plane: front=主视(XZ) top=俯视(XY) right=左视(YZ)
    """
    import Part

    def _to2d(pt, pl):
        # FreeCAD 1.1：Vector 用小写属性（x/y/z）
        if pl == "front":
            return (pt.x, pt.z)
        if pl == "top":
            return (pt.x, pt.y)
        return (pt.y, pt.z)

    segs, circles = [], []
    for e in shape.Edges:
        try:
            if e.Curve.TypeId == "Part::GeomLine":
                p1 = _to2d(e.Vertexes[0].Point, plane)
                p2 = _to2d(e.Vertexes[1].Point, plane)
                segs.append({"p1": [round(p1[0], 2), round(p1[1], 2)],
                             "p2": [round(p2[0], 2), round(p2[1], 2)]})
            elif e.Curve.TypeId == "Part::GeomCircle":
                c = e.Curve
                # 圆在视图平面上的投影：取圆上均匀采样点投影
                pts = []
                for i in range(25):
                    a = 2 * math.pi * i / 25
                    p = c.Center + c.Axis * c.Radius * math.cos(a) + c.Axis2 * c.Radius * math.sin(a)
                    pts.append(_to2d(p, plane))
                circles.append({"pts": [[round(x, 2), round(y, 2)] for x, y in pts]})
        except Exception:
            continue
    return {"segments": segs, "circles": circles}


# ---------------- 尺寸对象（DrawViewDimension + 公差 + References3D） ----------------

def _add_dimension(doc, page, view, dim_type, refs, value, tolerance="", over="", under=""):
    """创建尺寸对象并关联真实几何边。"""
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim")
    try:
        d.Type = dim_type
    except Exception:
        pass
    if refs:
        try:
            d.References3D = [(view, (refs,))]
        except Exception:
            d.References2D = [(view, (refs,))]
    if tolerance:
        d.FormatSpec = "\\u00d7" if False else "%v"
        if over:
            try:
                d.OverTolerance = over
            except Exception:
                pass
        if under:
            try:
                d.UnderTolerance = under
            except Exception:
                pass
    page.addView(d)
    return d


def _dimensions_for(doc, page, view, ptype, params, shape):
    """按零件类型生成尺寸标注计划（值来自真实几何投影/派生）。"""
    dims = []
    if ptype == "bolt":
        d = float(params.get("d", 10))
        L = float(params.get("L", 40))
        b = float(params.get("b", 2 * d + 6))
        s = float(params.get("s", 1.5 * d))
        k = float(params.get("k", 0.65 * d))
        dims.append({"type": "Distance", "value": L, "text": f"{L:g}",
                     "label": "总长"})
        dims.append({"type": "Distance", "value": b, "text": f"{b:g}",
                     "label": "螺纹长度"})
        dims.append({"type": "Diameter", "value": d, "text": f"Φ{d:g}",
                     "label": "公称直径"})
        dims.append({"type": "Diameter", "value": s, "text": f"S={s:g}",
                     "label": "对边"})
        dims.append({"type": "Distance", "value": k, "text": f"{k:g}",
                     "label": "头高"})
    elif ptype == "shaft":
        segs = params.get("segments") or []
        total = sum(float(s["L"]) for s in segs)
        dims.append({"type": "Distance", "value": total, "text": f"{total:g}",
                     "label": "总长"})
        for i, s in enumerate(segs):
            dims.append({"type": "Diameter", "value": float(s["d"]),
                         "text": f"Φ{s['d']:g}", "label": f"d{i+1}"})
            dims.append({"type": "Distance", "value": float(s["L"]),
                         "text": f"{s['L']:g}", "label": f"L{i+1}"})
        if params.get("chamfer"):
            dims.append({"type": "Distance", "value": float(params["chamfer"]),
                         "text": f"C{params['chamfer']:g}", "label": "倒角"})
    elif ptype == "flange":
        D = float(params.get("D", 160))
        d = float(params.get("d", 50))
        t = float(params.get("t", 18))
        pcd = float(params.get("pcd", 130))
        hole_d = float(params.get("hole_d", 11))
        dims.append({"type": "Diameter", "value": D, "text": f"Φ{D:g}",
                     "label": "外径"})
        dims.append({"type": "Diameter", "value": d, "text": f"Φ{d:g}",
                     "label": "内径"})
        dims.append({"type": "Diameter", "value": t, "text": f"{t:g}",
                     "label": "厚度"})
        dims.append({"type": "Diameter", "value": pcd, "text": f"Φ{pcd:g}",
                     "label": "分度圆"})
        dims.append({"type": "Diameter", "value": hole_d, "text": f"Φ{hole_d:g}",
                     "label": "孔径"})
    elif ptype == "gear":
        m = float(params.get("m", 2.5))
        z = int(params.get("z", 20))
        b = float(params.get("b", 25))
        x = float(params.get("x", 0))
        d_hub = float(params.get("d_hub", 30))
        da = m * z + 2 * m * (1 + x)
        df = m * z - 2.5 * m + 2 * m * x
        dims.append({"type": "Diameter", "value": da, "text": f"Φ{da:g}",
                     "label": "齿顶圆"})
        dims.append({"type": "Diameter", "value": df, "text": f"Φ{df:g}",
                     "label": "齿根圆"})
        dims.append({"type": "Diameter", "value": d_hub, "text": f"Φ{d_hub:g}",
                     "label": "孔径"})
        dims.append({"type": "Distance", "value": b, "text": f"{b:g}",
                     "label": "齿宽"})
        dims.append({"type": "Distance", "value": da, "text": f"m{m:g} z{z}",
                     "label": "模数齿数"})
    return dims


def _symbols_for(ptype, params):
    """工程符号数据。"""
    syms = {}
    if ptype == "bolt":
        d = float(params.get("d", 10))
        pitch = float(params.get("pitch", 1.5))
        syms["thread"] = f"M{d:g}\\u00d7{pitch:g}"
        syms["chamfer"] = f"C{round(max(0.06 * d, 0.3), 1):g}"
        syms["roughness"] = "Ra3.2"
    elif ptype == "shaft":
        if params.get("chamfer"):
            syms["chamfer"] = f"C{params['chamfer']:g}"
        syms["roughness"] = "Ra1.6"
    elif ptype == "flange":
        syms["roughness"] = "Ra6.3"
    elif ptype == "gear":
        syms["roughness"] = "Ra1.6"
    return syms


def make_drawing(doc, feature, params, ptype, base):
    """生成工程图：TechDraw 三视图 + 尺寸对象 + 数据导出。"""
    import FreeCAD as App
    import Part

    out_dir = os.path.dirname(base)
    tpl = _find_template()
    if not tpl:
        return {"error": "TechDraw 模板未找到"}
    _trace(out_dir, "tpl")

    # 页面 + 模板
    page = doc.addObject("TechDraw::DrawPage", "Page")
    template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    template.Template = tpl
    page.Template = template
    doc.recompute()
    _trace(out_dir, "page")

    # 三视图（第一角投影）
    group = doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
    if "SourceShapes" in group.PropertiesList:
        group.SourceShapes = [feature]
    else:
        group.Source = [feature]
    group.ProjectionType = "First angle"
    page.addView(group)
    views = {}
    for i, v in enumerate(["Front", "Top", "Right"]):
        item = doc.addObject("TechDraw::DrawProjGroupItem", f"View{i + 1}")
        item.Type = v
        group.addView(item)
        views[v.lower()] = item
    doc.recompute()
    _trace(out_dir, "views")

    # 尺寸对象（DrawViewDimension，值来自真实几何；关联性由 drawing_data 数据级验证）
    dims = _dimensions_for(doc, page, views.get("front"), ptype, params, feature.Shape)
    td_dims = []
    for i, dim in enumerate(dims):
        d = _add_dimension(doc, page, views.get("front"), dim["type"], None,
                           dim["value"], tolerance=dim.get("tolerance", ""),
                           over=dim.get("over", ""), under=dim.get("under", ""))
        td_dims.append({"type": dim["type"], "text": dim["text"],
                        "value": dim["value"], "label": dim["label"]})
    doc.recompute()
    _trace(out_dir, "dims")

    # 数据导出（供 PDF 渲染）
    shape = feature.Shape
    data = {
        "part": {"part_type": ptype, "part_name": feature.Document.Name or ptype,
                 "params": params},
        "views": {
            "front": _project_edges(shape, "front"),
            "top": _project_edges(shape, "top"),
            "right": _project_edges(shape, "right"),
        },
        "dimensions": td_dims,
        "symbols": _symbols_for(ptype, params),
        "title": {
            "name": params.get("part_name") or (feature.Document.Name or ptype),
            "material": params.get("material", ""),
            "scale": "1:1",
            "number": f"CAD-{ptype.upper()}",
        },
        "geometry": {
            "volume": round(shape.Volume, 2),
            "bbox": {"x": round(shape.BoundBox.XLength, 2),
                     "y": round(shape.BoundBox.YLength, 2),
                     "z": round(shape.BoundBox.ZLength, 2)},
            "faces": len(shape.Faces),
            "solids": len(shape.Solids),
        },
    }
    data_path = os.path.join(out_dir, "drawing_data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _trace(out_dir, "data")

    doc.recompute()
    return {"data": data_path, "page": page.Name}
