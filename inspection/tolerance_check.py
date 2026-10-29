"""工程图公差检查：尺寸公差 / 形位公差 / 配合公差。

功能：
1. detect_missing   检测关键配合位置缺少公差标注 → 输出建议
   （"轴承安装位置建议添加H7公差"式提示）
2. validate_provided 校验用户标注（params.tolerances）：
   - 配合类别适用性（轴承位用间隙配合会被警告）
   - IT 等级范围
   - 关键位置覆盖完整性
3. check_tolerances 合并输出（集成到 rules.check）

用户标注格式（params.tolerances）：
    [{"feature": "轴承位1", "fit": "k6"}, {"feature": "毂孔", "fit": "H7/k6"}]
    feature 取值见 _KEY_ITEMS 的 key。
"""

import logging

from knowledge_base import gbt

log = logging.getLogger("inspection.tolerance_check")

LEVELS_CN = {"error": "错误", "warning": "警告", "info": "提示"}

# 关键配合位置定义（按零件）：
# key → (描述, 推荐公差, 适用零件)
_KEY_ITEMS = {
    "bearing_seat": ("轴承安装位", "k6", ["shaft"]),
    "keyway_width": ("键槽宽度", "JS9", ["shaft"]),
    "keyway_symmetry": ("键槽对称度", "对称度8级", ["shaft"]),
    "journal": ("轴颈(轴承位)直径", "IT6", ["shaft"]),
    "gear_hub": ("齿轮毂孔", "H7", ["gear"]),
    "flange_bore": ("法兰内孔", "H7", ["flange"]),
    "bolt_thread": ("螺纹中径", "6g", ["bolt"]),
}

# 位置 → 推荐配合/公差与标准（引用 gbt 知识库）
_RECOMMEND = {
    "bearing_seat": gbt.TOLERANCE_RECOMMENDATIONS["shaft_bearing_seat"],
    "keyway_width": gbt.TOLERANCE_RECOMMENDATIONS["shaft_keyway_width"],
    "keyway_symmetry": gbt.TOLERANCE_RECOMMENDATIONS["shaft_keyway_symmetry"],
    "journal": gbt.TOLERANCE_RECOMMENDATIONS["shaft_journal"],
    "gear_hub": gbt.TOLERANCE_RECOMMENDATIONS["gear_hub"],
    "flange_bore": gbt.TOLERANCE_RECOMMENDATIONS["flange_bore"],
    "bolt_thread": gbt.TOLERANCE_RECOMMENDATIONS["bolt_thread"],
}

# 轴承位配合必须为过渡/过盈（k6/m6/n6/p6），间隙配合定位不可靠
_BEARING_ALLOWED = ("k6", "m6", "n6", "p6", "k5", "m5")


def _issue(level, item, detail, suggestion, standard="", analysis=""):
    risk = {"error": "high", "warning": "medium", "info": "low"}[level]
    return {
        "level": level, "item": item, "detail": detail, "suggestion": suggestion,
        "category": "公差检查", "category_cn": "公差检查",
        "risk": risk, "risk_cn": {"high": "高风险", "medium": "中风险", "low": "低风险"}[risk],
        "analysis": analysis or detail, "recommendation": suggestion, "standard": standard,
    }


def _present_features(part_type: str, params: dict) -> list[str]:
    """识别模型中存在的关键配合位置。"""
    feats = []
    if part_type == "shaft":
        segs = [s for s in (params.get("segments") or []) if s.get("d", 0) > 0]
        if any(float(s["d"]) in (30, 35, 40, 45, 50, 55) for s in segs):
            feats.append("bearing_seat")
            feats.append("journal")
        if (params.get("keyway") or {}).get("enabled"):
            feats.append("keyway_width")
            feats.append("keyway_symmetry")
    elif part_type == "gear":
        if float(params.get("d_hub", 0) or 0) > 0:
            feats.append("gear_hub")
    elif part_type == "flange":
        if float(params.get("d", 0) or 0) > 0:
            feats.append("flange_bore")
    elif part_type == "bolt":
        if float(params.get("d", 0) or 0) > 0:
            feats.append("bolt_thread")
    return feats


def detect_missing(part_type: str, params: dict) -> list:
    """检测关键位置缺少公差标注 → 建议（info 级）。"""
    provided = params.get("tolerances") or []
    provided_keys = {str(t.get("feature", "")).lower() for t in provided}
    issues = []
    for feat in _present_features(part_type, params):
        if feat in provided_keys:
            continue
        label, default, _std, note = _recommend_for(feat)
        issues.append(_issue(
            "info", f"缺少公差：{_KEY_ITEMS[feat][0]}",
            f"{note}。当前未标注任何公差，将按 ISO 2768-mK（IT14）默认执行，"
            f"无法保证装配精度。",
            f"{_KEY_ITEMS[feat][0]}建议添加{default}公差",
            standard=_std,
            analysis=note,
        ))
    return issues


def _recommend_for(feat: str):
    """返回 (位置描述, 推荐公差, 依据标准, 工程说明)。"""
    label = _KEY_ITEMS[feat][0]
    default, standard, note = _RECOMMEND[feat]
    return label, default, standard, note


def validate_provided(part_type: str, params: dict) -> list:
    """校验用户标注的公差：配合类别适用性 + IT 等级 + 覆盖率。"""
    provided = params.get("tolerances") or []
    if not isinstance(provided, list) or not provided:
        return []
    issues = []
    provided_keys = set()

    for t in provided:
        feat = str(t.get("feature", "")).lower()
        fit = str(t.get("fit", "")).strip()
        it = t.get("it")
        provided_keys.add(feat)

        if feat not in _KEY_ITEMS:
            issues.append(_issue("warning", "未知位置", f"公差标注位置 '{t.get('feature')}' 不在关键位置清单中",
                                 "检查 feature 名称", standard="—"))
            continue
        if not fit and it is None:
            issues.append(_issue("warning", "标注无效", f"{_KEY_ITEMS[feat][0]}的标注缺少 fit 或 it 值",
                                 f"按推荐填写 {_KEY_ITEMS[feat][1]}"))
            continue

        # 轴承位配合类别校验：必须过渡/过盈
        if feat in ("bearing_seat", "journal"):
            base = fit.split("/")[-1] if "/" in fit else fit
            if base and base not in _BEARING_ALLOWED:
                issues.append(_issue(
                    "warning", f"轴承位配合不当：{fit}",
                    f"轴承内圈与轴推荐过渡/过盈配合（k6/m6），当前 {fit} 为"
                    f"{'间隙配合' if gbt.fit_type(fit) == 'clearance' else '非常用轴公差'}，"
                    "内圈在旋转载荷下可能松动窜动。",
                    "轴承安装位置建议添加k6（或m6）公差",
                    standard="GB/T 275-1993",
                    analysis="滚动轴承内圈受旋转载荷时与轴应为过盈/过渡配合，防止内圈与轴相对转动。"))
        # IT 等级范围
        if it is not None:
            try:
                grade = int(str(it).lstrip("ITit"))
                if grade < 4 or grade > 14:
                    issues.append(_issue("warning", f"IT 等级异常：IT{grade}",
                                         "IT 等级 4~14 以外属超精或自由公差，常规加工难以/无需保证",
                                         "采用 IT5~IT12 常用范围", standard="GB/T 1800.2"))
            except (TypeError, ValueError):
                issues.append(_issue("warning", "IT 等级格式错误", f"it='{it}' 无法解析",
                                     "使用数字（如 7）或 IT7 格式"))

    # 覆盖率检查
    present = _present_features(part_type, params)
    missing = [f for f in present if f not in provided_keys]
    if missing:
        labels = "、".join(_KEY_ITEMS[f][0] for f in missing)
        issues.append(_issue(
            "warning", "公差标注不完整",
            f"已标注部分公差，但仍有 {len(missing)} 个关键位置未覆盖：{labels}",
            f"补充标注：{'；'.join(_KEY_ITEMS[f][0] + _KEY_ITEMS[f][1] for f in missing)}"))
    return issues


def check_tolerances(part_type: str, params: dict) -> list:
    """公差检查总入口：检测缺失 + 校验标注。"""
    issues = []
    try:
        issues += detect_missing(part_type, params)
        issues += validate_provided(part_type, params)
    except Exception:
        log.exception("公差检查异常")
    return issues
