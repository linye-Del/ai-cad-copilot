"""FreeCAD 端 STEP 特征提取（基于 OpenCascade）。

用法（freecadcmd 无头执行）：
    freecadcmd.exe -c "exec(open(r'<本文件>', encoding='utf-8').read())" <step_path> <out_json>

输出 JSON：
{
  "faces": 面总数,
  "face_types": {平面: n, 圆柱面: n, ...},
  "faces_area": 表面积 mm²,
  "bbox": {x, y, z 尺寸 mm},
  "volume": 体积 mm³,
  "holes": [{"d": 孔径, "depth": 深度, "count": 同孔径数量}],
  "fillets": [{"r": 圆角半径}],
  "chamfers": 倒角特征数量,
  "wall_thickness": 回转体壁厚近似值列表,
  "min_edge": 最短边长度,
  "tiny_features": 微小特征数
}
"""

import json
import os
import sys
from collections import Counter


def classify_face(face):
    """面类型分类。"""
    st = face.Surface.TypeId
    if "Plane" in st:
        return "平面"
    if "Cylinder" in st:
        return "圆柱面"
    if "Cone" in st:
        return "圆锥面"
    if "Sphere" in st:
        return "球面"
    if "Torus" in st:
        return "圆环面"
    return "复杂面"


def face_extent(face, axis):
    """面沿指定轴的投影长度（用于圆柱面轴向深度估计）。"""
    bb = face.BoundBox
    return max(abs(getattr(bb, "XMax") - getattr(bb, "XMin")),
               abs(getattr(bb, "YMax") - getattr(bb, "YMin")),
               abs(getattr(bb, "ZMax") - getattr(bb, "ZMin")))


def _face_center(f):
    c = f.CenterOfMass
    return [round(c.x, 1), round(c.y, 1), round(c.z, 1)]


def extract(shape):
    import Part  # noqa: F401

    out = {}
    faces = shape.Faces
    out["faces"] = len(faces)
    out["solids"] = len(shape.Solids)
    out["edges"] = len(shape.Edges)
    out["vertices"] = len(shape.Vertexes)
    types = Counter(classify_face(f) for f in faces)
    out["face_types"] = dict(types)
    out["faces_area"] = round(shape.Area, 1)
    bb = shape.BoundBox
    out["bbox"] = {"x": round(bb.XLength, 2), "y": round(bb.YLength, 2), "z": round(bb.ZLength, 2)}
    out["bbox_center"] = [round((bb.XMin + bb.XMax) / 2, 1),
                          round((bb.YMin + bb.YMax) / 2, 1),
                          round((bb.ZMin + bb.ZMax) / 2, 1)]
    try:
        out["volume"] = round(shape.Volume, 1)
    except Exception:
        out["volume"] = None

    # ---- 孔特征：凹圆柱面（法向指向轴心）----
    holes = []
    radii = {}
    slot_faces = []  # 凹平面（槽/凹腔候选）
    for f in faces:
        if "Cylinder" in f.Surface.TypeId:
            surf = f.Surface
            r = surf.Radius
            # 判断凹/凸：取面上同参数点与法向，法向的径向分量指向轴心 → 凹面（孔）
            try:
                p = f.valueAt(0.5, 0.5)
                n = f.normalAt(0.5, 0.5)
            except Exception:
                continue
            axis = surf.Axis
            v = p - surf.Center
            v_axial = axis * v.dot(axis)
            v_radial = v - v_axial  # 指向轴心的径向分量方向
            inward = v_radial.dot(n) < 0
            if not inward:
                radii[round(r, 2)] = radii.get(round(r, 2), 0) + 1
                continue
            depth = face_extent(f, None)
            key = round(r * 2, 2)  # 直径
            holes.append({"d": key, "depth": round(depth, 1), "location": _face_center(f)})
        elif "Plane" in f.Surface.TypeId:
            # 凹平面 → 槽/凹腔候选：法向偏移点落在实体内部
            try:
                n = f.normalAt(0.5, 0.5)
                p = f.valueAt(0.5, 0.5)
                p_in = p + n * 0.05  # 沿法向（材料外方向）微移
                if shape.isInside(p_in, 0.01, True):
                    slot_faces.append(f)
            except Exception:
                continue
    # 按孔径合并计数（保留首个位置）
    hole_map = {}
    for h in holes:
        k = h["d"]
        if k not in hole_map:
            hole_map[k] = {"d": k, "depth": h["depth"], "count": 0,
                           "location": h["location"]}
        hole_map[k]["count"] += 1
        hole_map[k]["depth"] = max(hole_map[k]["depth"], h["depth"])
    out["holes"] = sorted(hole_map.values(), key=lambda x: x["d"])
    # 外圆柱统计（同半径面数，用于壁厚计算）
    out["outer_cylinders"] = radii

    # ---- 圆角特征：小半径圆柱面（R 0.2~8mm，轴向短）----
    fillets = Counter()
    fillet_locs = {}
    for f in faces:
        if "Cylinder" not in f.Surface.TypeId:
            continue
        r = f.Surface.Radius
        if 0.2 <= r <= 8:
            ext = face_extent(f, None)
            # 圆角面轴向长度通常小于直径（部分圆环带）
            if ext <= 4 * r + 2:
                rk = round(r, 2)
                fillets[rk] += 1
                if rk not in fillet_locs:
                    fillet_locs[rk] = _face_center(f)
    out["fillets"] = [{"r": r, "count": c, "location": fillet_locs.get(r, [0, 0, 0])}
                      for r, c in sorted(fillets.items())]

    # ---- 槽特征：凹平面组（排除面积小的倒角面）----
    slots = []
    for f in slot_faces:
        area = f.Area
        if area < 15.0:  # 小面积面 → 倒角/过渡面，排除
            continue
        bb = f.BoundBox
        # 槽侧壁特征宽度 = bbox 最大边（槽宽方向投影较大的一维）
        w = max(bb.XLength, bb.YLength, bb.ZLength)
        slots.append({"w": round(w, 1), "area": round(area, 1),
                      "location": _face_center(f)})
    out["slots"] = slots

    # ---- 内角检测：相邻平面材料侧角 < 75°（刀具无法清根的尖角）----
    # 性能保护：仅检查面积 >20mm² 的平面面（跳过齿面等微小面），最多 300 个
    concave_corners = []
    seen_pairs = set()
    checked = 0
    plane_candidates = [f for f in faces if "Plane" in f.Surface.TypeId and f.Area > 20.0]
    plane_candidates = sorted(plane_candidates, key=lambda x: -x.Area)[:300]
    for f in plane_candidates:
        checked += 1
        for e in f.Edges:
            if len(e.Faces) < 2:
                continue
            for adj in e.Faces:
                if adj.isSame(f) or "Plane" not in adj.Surface.TypeId:
                    continue
                pair = tuple(sorted((id(f), id(adj))))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                try:
                    mid = e.CenterOfMass
                    n_f = f.normalAt(0.5, 0.5)
                    n_a = adj.normalAt(0.5, 0.5)
                    # 材料侧角：两法向分别取外法向，材料侧角 = 180° - arccos(n_f·n_a)（凸角）
                    # 用面中心相对边中点的方向向量估计材料侧角
                    c_f = f.CenterOfMass
                    c_a = adj.CenterOfMass
                    v_f = c_f - mid
                    v_a = c_a - mid
                    v_f.normalize()
                    v_a.normalize()
                    import math as _m
                    cosang = max(-1.0, min(1.0, v_f.dot(v_a)))
                    ang = _m.degrees(_m.acos(cosang))  # 材料侧角近似
                    if ang < 75.0:
                        concave_corners.append({
                            "angle": round(ang, 1),
                            "location": [round(mid.x, 1), round(mid.y, 1), round(mid.z, 1)],
                        })
                except Exception:
                    continue
    out["concave_corners"] = concave_corners[:20]

    # ---- 倒角特征：窄平面且与相邻面呈 45° 左右夹角 ----
    chamfer_count = 0
    for f in faces:
        if "Plane" not in f.Surface.TypeId:
            continue
        bb = f.BoundBox
        w = min(bb.XLength, bb.YLength, bb.ZLength)
        if 0.2 <= w <= 5:  # 窄条平面，疑似倒角
            try:
                n = f.normalAt(0.5, 0.5)
            except Exception:
                continue
            for e in f.Edges[:8]:
                for adj in e.Faces:
                    if adj.isSame(f):
                        continue
                    if "Plane" in adj.Surface.TypeId:
                        try:
                            n2 = adj.normalAt(0.5, 0.5)
                            ang = abs(n.dot(n2))
                            if 0.45 <= ang <= 0.9:  # ~45°±
                                chamfer_count += 1
                        except Exception:
                            pass
    out["chamfers"] = chamfer_count

    # ---- 回转体壁厚近似：同轴外圆柱与内孔半径差 ----
    walls = []
    if holes:
        for h in holes:
            r_in = h["d"] / 2
            best = None
            for r_out in radii:
                if r_out > r_in:
                    gap = r_out - r_in
                    if best is None or gap < best:
                        best = gap
            if best is not None:
                walls.append({"hole_d": h["d"], "wall": round(best, 2)})
    out["wall_thickness"] = walls

    # ---- 微小特征 ----
    min_edge = 1e9
    tiny = 0
    for e in shape.Edges:
        l = e.Length
        if l < 0.01:
            continue
        min_edge = min(min_edge, l)
        if l < 1.0:
            tiny += 1
    out["min_edge"] = round(min_edge, 3) if min_edge < 1e8 else None
    out["tiny_features"] = tiny
    return out


def main():
    # 与 run_fc.py 相同的传参模式：过滤 freecadcmd 的 -c/--pass 等参数
    args = [
        a for a in sys.argv[1:]
        if a != "--pass" and not a.startswith("-c") and not a.startswith("exec(open")
    ]
    if len(args) < 2:
        print("缺少参数: step_path out_json", file=sys.stderr)
        sys.exit(1)
    step_path, out_path = args[0], args[1]
    import FreeCAD as App
    import Part

    try:
        shape = Part.Shape()
        shape.read(step_path)
        result = extract(shape)
        result["ok"] = True
    except Exception as e:
        import traceback
        result = {"ok": False, "error": traceback.format_exc()}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
