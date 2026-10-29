"""STEP 三维模型智能审查总入口。

流程：parse（实体解析）→ detect（特征识别）→ manufacturability（可制造性）
      → design check（机械设计：应力集中/不合理结构/装配风险）→ 报告

输出 CAD Review Report：
    {"feature": 特征, "location": 位置, "problem": 问题, "risk": 风险等级,
     "suggestion": 建议, "engineering_reason": 工程解释}
"""

import json
import logging
import os
import time

from config import settings
from inspection import feature_detector, manufacturability_checker, step_parser

log = logging.getLogger("inspection.step_review")

RISK_CN = {"high": "高风险", "medium": "中风险", "low": "低风险"}


def _issue(feature, location, problem, risk, suggestion, reason):
    return {
        "feature": feature, "location": location, "problem": problem,
        "risk": risk, "risk_cn": RISK_CN.get(risk, risk),
        "suggestion": suggestion, "engineering_reason": reason,
        # 兼容旧字段（step_reviewer / 前端）
        "level": {"high": "error", "medium": "warning", "low": "info"}[risk],
        "solution": suggestion, "item": f"{feature}：{problem}",
        "detail": reason, "standard": "机械加工工艺学 / 机械设计手册",
    }


def design_check(parsed: dict, features: list[dict]) -> list[dict]:
    """机械设计检查：应力集中 / 不合理结构 / 装配风险。"""
    issues = []

    # 1. 应力集中位置
    for r in feature_detector.stress_risers(parsed, features):
        issues.append(_issue(
            r["feature"], r["location"], "应力集中位置",
            "medium", "增加过渡圆角或卸荷槽，避免尖角/小圆角",
            r["reason"]))

    # 2. 不合理结构：微小特征过多（模型噪声/无法加工细节）
    tiny = parsed.get("tiny_features", 0)
    if tiny > 50:
        issues.append(_issue(
            "微小特征", "整体",
            f"检测到 {tiny} 处 <1mm 微小边特征，模型细节不合理",
            "medium", "简化细节（如去除装饰性小特征、螺纹省略表达）",
            "过小的特征无法用常规刀具加工，且放大应力集中与测量误差"))

    # 3. 装配风险：深孔盲孔 + 孔壁过薄组合
    holes = parsed.get("holes") or []
    thin_holes = [h for h in holes
                  if any(w["hole_d"] == h["d"] and w["wall"] < 3 for w in parsed.get("wall_thickness") or [])]
    if thin_holes:
        for h in thin_holes:
            issues.append(_issue(
                f"孔 φ{h['d']}", feature_detector._loc_text(h.get("location"), parsed.get("bbox_center")),
                "孔壁过薄，装配压装/螺栓预紧可能破裂",
                "high", "增大孔间距或加厚壁部，评估装配载荷",
                "薄孔壁在压装或螺栓预紧产生的环向应力下易开裂"))

    # 4. 实体数量异常（多实体装配模型被当单件审查）
    if parsed.get("solids", 1) > 1:
        issues.append(_issue(
            "多实体", "整体", f"包含 {parsed['solids']} 个独立实体",
            "low", "确认是否为装配体；单件制造应合并实体",
            "多实体模型可能为装配体，尺寸链与配合需按装配件审查"))
    return issues


def review_step(step_path: str, out_dir: str | None = None) -> dict:
    """STEP 智能审查主入口（保持与旧 review_step 接口兼容）。"""
    t0 = time.time()
    parsed = step_parser.parse_step(step_path, out_dir)
    features = feature_detector.detect_features(parsed)
    problems = (manufacturability_checker.check(parsed, features)
                + design_check(parsed, features))
    report = {
        "features": parsed,
        "feature_list": features,
        "problems": problems,
        "passed": len(problems) == 0,
        "time_s": round(time.time() - t0, 1),
    }
    # 落盘 reports/
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.basename(step_path).replace(".step", "").replace(".STEP", "")
    path = settings.get_reports_dir() / f"{stamp}_step_review_{base}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(path)
    log.info("STEP 智能审查完成 %s: %d 项问题", os.path.basename(step_path), len(problems))
    return report
