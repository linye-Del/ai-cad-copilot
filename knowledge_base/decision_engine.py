"""Engineering Decision Engine —— 工程决策引擎。

让 AI 不仅生成 CAD，还能解释设计依据（正向设计咨询）：
  输入：载荷（扭矩）+ 轴径 + 长度 + 材料
  输出：
    - 当前设计风险（高/中/低）+ 原因
    - 推荐轴径范围（含安全系数）
    - 材料建议（按载荷分级）
    - 加工工艺 / 装配配合 / 标准库 检查（五字段规则格式）

规则格式统一：
    {condition, analysis, risk, recommendation, standard}
"""

import logging
import math

from knowledge_base import gbt

log = logging.getLogger("knowledge_base.decision_engine")

# 材料 → (许用扭转应力 [τ] MPa, 屈服强度 σs MPa, 说明)
MATERIAL_PROPS = {
    "Q235": (25, 235, "普通碳素钢，轻载结构件"),
    "45钢": (40, 355, "优质碳钢，调质 217~255HBW，通用轴类"),
    "45": (40, 355, "优质碳钢，调质 217~255HBW，通用轴类"),
    "40Cr": (55, 785, "合金钢，调质+表面淬火，重要轴类"),
    "35CrMo": (60, 835, "合金钢，调质，高强/高温轴类"),
    "42CrMo": (60, 930, "合金钢，调质，重载轴类"),
    "304": (35, 205, "奥氏体不锈钢，耐蚀但强度低"),
    "316": (35, 205, "奥氏体不锈钢，耐蚀但强度低"),
    "6061铝": (50, 276, "铝合金，轻量化，许用应力低（取剪切强度折算）"),
}

# 扭矩 → 推荐材料（经验分级）
TORQUE_MATERIAL = [
    (100, "Q235 或 45钢（正火/调质）", "轻载传动"),
    (500, "45钢（调质 217~255HBW）", "通用传动轴"),
    (2000, "40Cr（调质+表面淬火）", "中重载传动"),
    (float("inf"), "35CrMo / 42CrMo（调质）", "重载/冲击载荷"),
]


def _tau_allow(material: str) -> float:
    return MATERIAL_PROPS.get(material, MATERIAL_PROPS["45钢"])[0]


def _sigma_yield(material: str) -> float:
    return MATERIAL_PROPS.get(material, MATERIAL_PROPS["45钢"])[1]


def shaft_min_diameter(torque_nm: float, material: str = "45钢") -> float:
    """满足 [τ] 的最小轴径（mm）。"""
    tau = _tau_allow(material)
    return (16 * torque_nm * 1000 / (math.pi * tau)) ** (1 / 3)


def safety_factor(torque_nm: float, diameter: float, material: str = "45钢") -> float:
    """按扭转应力计算安全系数 n = [τ] / τ_actual。"""
    if diameter <= 0:
        return 0.0
    tau = _tau_allow(material)
    tau_actual = 16 * torque_nm * 1000 / (math.pi * diameter ** 3)
    return round(tau / tau_actual, 2) if tau_actual > 0 else 0.0


def recommend_material(torque_nm: float) -> str:
    for limit, mat, note in TORQUE_MATERIAL:
        if torque_nm <= limit:
            return f"{mat}（{note}）"
    return ""


def analyze_shaft(torque_nm: float, diameter: float,
                  length: float = 0, material: str = "45钢") -> dict:
    """轴类参数合理性分析（正向设计咨询）。

    返回五字段规则格式 + 设计推荐数据。
    """
    d_min = shaft_min_diameter(torque_nm, material)
    n = safety_factor(torque_nm, diameter, material)
    d_reco_low = math.ceil(d_min * 1.08 / 5) * 5      # 考虑键槽削弱
    d_reco_high = math.ceil(d_min * 1.3 / 5) * 5      # 推荐上限（留裕度）

    # 风险判定
    if n < 1.0:
        risk, level = "高风险", "high"
        cause = f"τ=16T/(πd³)={16 * torque_nm * 1000 / (math.pi * diameter ** 3):.1f}MPa 超过材料许用应力 [τ]={_tau_allow(material)}MPa，扭矩下安全裕度不足"
        suggest = f"轴径增加至 {d_reco_low}mm（安全系数 ≥1.08）"
    elif n < 1.5:
        risk, level = "中风险", "medium"
        cause = f"安全系数 n={n} < 1.5，交变/冲击载荷下裕度偏紧"
        suggest = f"轴径建议增加至 {d_reco_high}mm（n≥1.5），或改用高强度材料"
    else:
        risk, level = "低风险", "low"
        cause = f"安全系数 n={n} ≥ 1.5，满足 {material} 扭转强度要求"
        suggest = "当前轴径满足强度要求，可按图设计"

    analysis = (f"扭矩 T={torque_nm:g}N·m，轴径 d={diameter:g}mm，材料 {material}："
                f"实际扭转应力 τ={16 * torque_nm * 1000 / (math.pi * diameter ** 3):.1f}MPa，"
                f"许用 [τ]={_tau_allow(material)}MPa，安全系数 n={n}。")

    return {
        "condition": f"扭矩 {torque_nm:g}N·m / 轴径 {diameter:g}mm / 材料 {material}",
        "analysis": analysis,
        "risk": risk,
        "risk_level": level,
        "recommendation": suggest,
        "standard": "GB/T 699（材料力学性能）/ 机械设计手册（扭转强度校核）",
        # 设计推荐数据
        "design": {
            "torque_nm": torque_nm,
            "diameter": diameter,
            "material": material,
            "length": length,
            "tau_actual_mpa": round(16 * torque_nm * 1000 / (math.pi * diameter ** 3), 1),
            "tau_allow_mpa": _tau_allow(material),
            "d_min_mm": round(d_min, 1),
            "recommend_d_range_mm": [d_reco_low, d_reco_high],
            "safety_factor": n,
            "recommend_material": recommend_material(torque_nm),
            "sigma_yield_mpa": _sigma_yield(material),
        },
    }


# ---------------- 工艺 / 装配 / 标准检查（复用决策系统规则） ----------------

def evaluate_design(part_type: str, params: dict,
                    torque_nm: float | None = None) -> dict:
    """设计总评估：参数合理性 + 加工工艺 + 装配配合 + 标准库。

    返回设计报告结构（五字段规则列表 + 轴分析）。
    """
    from inspection import rules as rc

    issues = rc.check(part_type, params, torque_nm=torque_nm)
    result = {
        "part_type": part_type,
        "params": params,
        "torque_nm": torque_nm,
        "issues": issues,
        "passed": not any(i.get("level") in ("error", "warning") for i in issues),
        "rules_count": len(issues),
        "categories": {},
    }
    for i in issues:
        cat = i.get("category_cn", "其他")
        result["categories"].setdefault(cat, []).append(i)

    # 轴参数合理性分析（若提供载荷与轴段）
    if torque_nm and part_type == "shaft":
        segs = [s for s in (params.get("segments") or []) if s.get("d", 0) > 0]
        if segs:
            d_min_seg = min(float(s["d"]) for s in segs)
            total_l = sum(float(s.get("L", 0) or 0) for s in segs)
            result["shaft_analysis"] = analyze_shaft(
                torque_nm, d_min_seg, total_l, str(params.get("material", "45钢")))
    return result
