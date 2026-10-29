"""特征检测器：将 STEP 解析结果语义化为几何特征列表。

识别：
    孔 / 槽 / 圆角 / 倒角 / 壁厚 / 内角
每个特征带 size（尺寸）与 location（位置，mm 坐标 + 相对描述）。

另输出应力集中候选位置（机械设计检查用）：
    - 小圆角（R<1mm）+ 直径突变
    - 键槽端部
"""

import logging

log = logging.getLogger("inspection.feature_detector")


def _loc_text(loc, bbox_center=None):
    """坐标 → 位置描述（含相对整体位置）。"""
    if not loc or all(v == 0 for v in loc):
        return "整体/未知"
    x, y, z = loc
    txt = f"({x}, {y}, {z})mm"
    if bbox_center:
        parts = []
        for i, axis in enumerate(("X", "Y", "Z")):
            if abs(loc[i] - bbox_center[i]) < max(2.0, abs(bbox_center[i]) * 0.15):
                parts.append(f"{axis}向居中")
            elif loc[i] < bbox_center[i] - max(2.0, abs(bbox_center[i]) * 0.15):
                parts.append(f"{axis}向偏小端")
            else:
                parts.append(f"{axis}向偏大端")
        if parts:
            txt = "、".join(parts) + " 处 " + txt
    return txt


def detect_features(parsed: dict) -> list[dict]:
    """语义化特征列表。"""
    bbox = parsed.get("bbox_center") or [0, 0, 0]
    feats = []

    # 孔
    for h in parsed.get("holes") or []:
        feats.append({
            "kind": "孔", "d": h["d"], "depth": h.get("depth"),
            "count": h.get("count", 1), "size": f"φ{h['d']}",
            "location": h.get("location") or [0, 0, 0],
            "location_txt": _loc_text(h.get("location"), bbox),
        })
    # 槽/凹腔
    for s in parsed.get("slots") or []:
        feats.append({
            "kind": "槽", "w": s["w"], "area": s.get("area"),
            "count": 1, "size": f"宽~{s['w']}mm",
            "location": s.get("location") or [0, 0, 0],
            "location_txt": _loc_text(s.get("location"), bbox),
        })
    # 圆角
    for f in parsed.get("fillets") or []:
        feats.append({
            "kind": "圆角", "r": f["r"], "count": f.get("count", 1),
            "size": f"R{f['r']}", "location": f.get("location") or [0, 0, 0],
            "location_txt": _loc_text(f.get("location"), bbox),
        })
    # 倒角（窄平面数）
    cham = parsed.get("chamfers") or 0
    if cham:
        feats.append({
            "kind": "倒角", "count": cham, "size": f"{cham} 处",
            "location": [0, 0, 0], "location_txt": "多处（45° 斜面）",
        })
    # 壁厚（回转体近似）
    for w in parsed.get("wall_thickness") or []:
        feats.append({
            "kind": "壁厚", "wall": w["wall"], "hole_d": w["hole_d"],
            "size": f"{w['wall']}mm", "location": [0, 0, 0],
            "location_txt": f"φ{w['hole_d']} 孔周围",
        })
    # 内角
    for c in parsed.get("concave_corners") or []:
        feats.append({
            "kind": "内角", "angle": c["angle"], "size": f"{c['angle']}°",
            "location": c.get("location") or [0, 0, 0],
            "location_txt": _loc_text(c.get("location"), bbox),
        })
    return feats


def stress_risers(parsed: dict, features: list[dict]) -> list[dict]:
    """应力集中候选位置（机械设计检查输入）。"""
    risers = []
    bbox = parsed.get("bbox_center") or [0, 0, 0]
    # 1. 小圆角
    for f in parsed.get("fillets") or []:
        if f["r"] < 1.0:
            risers.append({
                "feature": f"圆角 R{f['r']}",
                "location": _loc_text(f.get("location"), bbox),
                "reason": "小半径圆角处应力集中系数 Kt 高",
            })
    # 2. 键槽端部（槽特征端点即应力集中位置；按宽度分组合并，避免齿槽类重复报警）
    from collections import Counter
    slot_counts = Counter()
    slot_locs = {}
    for s in parsed.get("slots") or []:
        if s.get("area", 0) > 50:  # 真实槽（非小过渡面）
            key = round(s["w"], 0)
            slot_counts[key] += 1
            slot_locs.setdefault(key, s.get("location") or [0, 0, 0])
    for w, cnt in sorted(slot_counts.items()):
        risers.append({
            "feature": f"槽（宽~{w}mm）×{cnt}",
            "location": _loc_text(slot_locs[w], bbox),
            "reason": "键槽/槽端部尖角应力集中（Kt≈1.5~2.5）",
        })
    return risers
