"""可制造性检查器：基于 STEP 解析结果执行制造可行性评估。

规则：
    最小壁厚    —— 薄壁变形/破裂风险
    最小圆角    —— 刀具半径限制
    深孔加工    —— 深径比 >8 钻削风险
    内角无法加工 —— 尖角 <75° 刀具无法清根
    薄壁变形    —— 大面积薄壁刚性不足
"""

import logging

from inspection import feature_detector

log = logging.getLogger("inspection.manufacturability_checker")

MIN_WALL = 1.5      # 机加工最小壁厚（mm）
MIN_FILLET = 0.5    # 最小可加工圆角（mm）
DEEP_HOLE_RATIO = 8.0
SHARP_ANGLE = 75.0  # 内角临界角（度）


def _issue(feature, location, problem, risk, suggestion, reason):
    return {
        "feature": feature, "location": location, "problem": problem,
        "risk": risk, "suggestion": suggestion,
        "engineering_reason": reason,
        # 兼容旧字段
        "level": {"high": "error", "medium": "warning", "low": "info"}[risk],
        "solution": suggestion, "item": f"{feature}：{problem}",
        "detail": reason,
    }


def check(parsed: dict, features: list[dict] | None = None) -> list[dict]:
    """可制造性检查，返回问题列表。"""
    issues = []
    if features is None:
        features = feature_detector.detect_features(parsed)

    # 1. 最小壁厚
    for w in parsed.get("wall_thickness") or []:
        wall = w["wall"]
        if wall < MIN_WALL:
            issues.append(_issue(
                f"壁厚 {wall}mm（φ{w['hole_d']} 孔周围）",
                f"φ{w['hole_d']} 孔周围",
                f"壁厚仅 {wall}mm，低于机加工最小壁厚 {MIN_WALL}mm",
                "high",
                "增大壁厚至 ≥3mm，或改铸造/焊接工艺并评估变形",
                "薄壁件在切削力与残余应力作用下易变形，且刚性不足影响加工精度"))
    # 2. 最小圆角
    for f in parsed.get("fillets") or []:
        if f["r"] < MIN_FILLET:
            issues.append(_issue(
                f"圆角 R{f['r']}",
                feature_detector._loc_text(f.get("location"), parsed.get("bbox_center")),
                f"圆角 R{f['r']} < 最小可加工圆角 {MIN_FILLET}mm",
                "medium",
                "圆角加大至 R0.5 以上，或改用小半径刀具+多次走刀",
                "铣削圆角受刀具半径限制，R<0.5mm 需专用刀具且易断刀"))
    # 3. 深孔加工
    for h in parsed.get("holes") or []:
        d, depth = h["d"], h.get("depth") or 0
        if d > 0 and depth / d > DEEP_HOLE_RATIO:
            issues.append(_issue(
                f"孔 φ{d}（深 {depth}）",
                feature_detector._loc_text(h.get("location"), parsed.get("bbox_center")),
                f"深径比 {depth / d:.1f} > {DEEP_HOLE_RATIO}，属于深孔",
                "medium",
                "分段钻孔（阶梯孔）、镗削或改用喷吸钻",
                "深孔钻削时钻头刚度不足易偏斜，排屑困难，孔径公差难保证"))
    # 4. 内角无法加工
    for c in parsed.get("concave_corners") or []:
        issues.append(_issue(
            f"内尖角 {c['angle']}°",
            feature_detector._loc_text(c.get("location"), parsed.get("bbox_center")),
            f"内角 {c['angle']}° < {SHARP_ANGLE}°，刀具无法清根",
            "medium",
            "内角处增加 R1~R3 圆角过渡，或改线切割/EDM",
            "铣刀在尖角处无法完全清根，残留材料导致应力集中与装配干涉"))
    # 5. 薄壁变形（大面积薄壁）
    thin_area = _thin_wall_area(parsed)
    if thin_area:
        issues.append(_issue(
            "大面积薄壁",
            "整体",
            f"检测到薄壁区域总面积约 {thin_area}mm²，加工变形风险高",
            "medium",
            "增加加强筋、分序加工（粗加工后时效再精加工）",
            "大面积薄壁在切削热与残余应力作用下翘曲变形，尺寸超差"))
    return issues


def _thin_wall_area(parsed: dict) -> float | None:
    """薄壁面积估算：壁厚 <3mm 且对应孔周围的大面积。"""
    total = 0.0
    for w in parsed.get("wall_thickness") or []:
        if w["wall"] < 3.0:
            total += (w.get("wall") or 0) * 100  # 粗略面积（壁厚×孔周向展开）
    return round(total) if total else None
