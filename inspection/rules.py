"""机械设计决策检查：基础硬性检查 + 决策系统（四大类别规则）。

check() 输出统一问题条目，字段：
  level / item / detail / suggestion        （兼容旧前端）
  category / analysis / risk / standard     （工程解释扩展）
"""

import math
import os

from cad_engine.parts.base import BOLT_STD
from knowledge_base import rules as decision_engine

LEVELS = {"error": "错误", "warning": "警告", "info": "提示"}


def _issue(level, item, detail, suggestion, category="基础检查", risk="medium",
           analysis="", standard="机械设计常识"):
    return {
        "level": level, "item": item, "detail": detail, "suggestion": suggestion,
        "category": category, "category_cn": category,
        "risk": risk, "risk_cn": {"high": "高风险", "medium": "中风险", "low": "低风险"}[risk],
        "analysis": analysis or detail, "recommendation": suggestion, "standard": standard,
    }


# 基础检查：仅保留硬性错误与几何矛盾（软性规则统一交由决策系统输出）

def check_bolt(p):
    issues = []
    d = float(p.get("d", 0))
    L = float(p.get("L", 0))
    b = float(p.get("b", 0))
    if d <= 0 or L <= 0:
        issues.append(_issue("error", "基本尺寸", "直径/长度必须大于0", "请修正参数",
                             risk="high", standard="GB/T 5782"))
        return issues
    if b > L:
        issues.append(_issue("error", "螺纹长度", f"螺纹长度 b={b}mm 超过杆长 L={L}mm",
                             "缩短螺纹或加长螺栓", risk="high"))
    if L > 2 * d + 6 and b >= L - 0.5:
        issues.append(_issue("warning", "螺纹长度", f"GB/T 5782 规定 L>{2*d+6}mm 时螺纹长度应为 2d+6={round(2*d+6,1)}mm",
                             "按标准设置 b", analysis="GB/T 5782 限定螺栓全螺纹长度，保证旋合承载与制造经济性。",
                             risk="medium", standard="GB/T 5782-2016"))
    return issues


def check_shaft(p):
    issues = []
    segs = p.get("segments") or []
    if not segs:
        issues.append(_issue("error", "轴段", "未定义任何轴段", "至少一段 直径×长度", risk="high"))
        return issues
    for i, s in enumerate(segs):
        d = float(s.get("d", 0))
        L = float(s.get("L", 0))
        if d <= 0 or L <= 0:
            issues.append(_issue("error", f"轴段{i+1}", f"直径或长度无效 (d={d}, L={L})", "修正该段尺寸", risk="high"))
    return issues


def check_flange(p):
    issues = []
    D = float(p.get("D", 0))
    d = float(p.get("d", 0))
    t = float(p.get("t", 0))
    n = int(p.get("n", 0))
    pcd = float(p.get("pcd", 0))
    hole_d = float(p.get("hole_d", 0))
    if D <= d:
        issues.append(_issue("error", "尺寸", f"外径 D={D}mm 必须大于内径 d={d}mm", "修正尺寸", risk="high"))
    if n < 2:
        issues.append(_issue("error", "螺栓孔数", f"螺栓孔数 n={n} 过少", "至少2个", risk="high"))
    elif n not in (4, 8, 12, 16):
        issues.append(_issue("info", "螺栓孔数", f"n={n} 非常用系列（4/8/12/16）", "建议改为常用数",
                             analysis="4/8/12/16 为法兰孔数常用系列，对应分度圆整倍数与密封均匀性。",
                             standard="GB/T 9116 法兰连接习惯"))
    if pcd <= d + hole_d / 2:
        issues.append(_issue("error", "分度圆", f"分度圆直径 {pcd}mm 与内孔干涉", "增大分度圆", risk="high"))
    if pcd + hole_d / 2 > D - 4:
        issues.append(_issue("error", "分度圆", f"分度圆直径 {pcd}mm 超出外径范围", "减小分度圆或增大外径", risk="high"))
    if hole_d < 6:
        issues.append(_issue("warning", "螺栓孔径", f"孔径 {hole_d}mm 偏小", "检查螺栓规格"))
    return issues


def check_gear(p):
    issues = []
    m = float(p.get("m", 0))
    z = int(p.get("z", 0))
    b = float(p.get("b", 0))
    alpha = float(p.get("alpha", 20))
    x = float(p.get("x", 0))
    d_hub = float(p.get("d_hub", 0))
    if m <= 0 or z <= 0:
        issues.append(_issue("error", "基本参数", "模数与齿数必须大于0", "修正参数", risk="high"))
        return issues
    d = m * z
    da = d + 2 * m * (1 + x)
    df = d - 2.5 * m + 2 * m * x
    db = d * math.cos(math.radians(alpha))
    if z < 17 and x < (17 - z) / 17.0:
        issues.append(_issue("warning", "齿数", f"z={z}<17 且未足够正变位，加工会产生根切", "增大齿数或变位 x≥{:.3f}".format((17 - z) / 17.0),
                             analysis="标准齿轮 z<17 时滚齿将发生根切，削弱齿根强度并影响啮合；"
                                      "正变位可避免根切。",
                             risk="medium", standard="GB/T 1356-2001（渐开线齿轮基本齿廓）"))
    if z < 12:
        issues.append(_issue("error", "齿数", f"z={z} 过小，传动不平稳", "增大齿数", risk="high"))
    if b <= 0:
        issues.append(_issue("error", "齿宽", "齿宽必须大于0", "修正"))
    else:
        ratio = b / d
        if ratio > 1.5:
            issues.append(_issue("warning", "齿宽系数", f"齿宽系数 b/d={ratio:.2f} 过大，齿向载荷不均",
                                 "减小齿宽", analysis="齿宽系数过大时齿向载荷分布不均度上升，需提高制造精度或采用鼓形齿。",
                                 risk="medium"))
        if ratio < 0.1:
            issues.append(_issue("info", "齿宽系数", f"齿宽系数 b/d={ratio:.2f} 过小", "适当加宽"))
    if da < d_hub:
        issues.append(_issue("error", "尺寸", "齿顶圆小于孔径，几何矛盾", "修正参数", risk="high"))
    if db > da:
        issues.append(_issue("error", "几何", "基圆大于齿顶圆，齿形无法生成", "增大齿数或模数", risk="high"))
    return issues


CHECKERS = {"bolt": check_bolt, "shaft": check_shaft, "flange": check_flange, "gear": check_gear}


def check(part_type: str, params: dict, torque_nm: float | None = None) -> list:
    """组合检查：基础硬性检查 + 机械设计决策系统 + 工程图公差检查。"""
    fn = CHECKERS.get(part_type)
    issues = fn(params) if fn else [
        _issue("info", "类型", f"未知零件类型 {part_type}", "检查参数")
    ]
    # 决策系统规则（带工程解释与标准依据）
    decision = decision_engine.evaluate(part_type, params, torque_nm=torque_nm)
    issues.extend(decision)
    # 工程图公差检查（尺寸/形位/配合公差，H7/g6、H8/f7、IT 等级）
    from inspection import tolerance_check

    issues.extend(tolerance_check.check_tolerances(part_type, params))
    return issues


def check_outputs(result: dict) -> list:
    issues = []
    files = result.get("files", {})
    for key in ["fcstd", "step", "stl"]:
        if not files.get(key) or not os.path.isfile(files[key]):
            issues.append(_issue("error", "输出文件", f"{key} 未生成", "检查建模日志", risk="high"))
    drawing = result.get("drawing", {})
    if drawing.get("error"):
        issues.append(_issue("error", "工程图", drawing["error"], "检查 TechDraw 日志", risk="high"))
    elif not any(k in drawing for k in ("svg", "pdf", "dxf")):
        issues.append(_issue("warning", "工程图", "工程图未成功导出任何格式", "检查导出日志"))
    return issues


def rules_summary() -> dict:
    """决策系统规则库概览（文档/演示用）。"""
    return decision_engine.summary()
