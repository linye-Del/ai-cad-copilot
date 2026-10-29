"""机械设计决策系统：规则引擎核心。

规则格式（五字段 + 元数据）：
    condition:     触发条件描述（人读）
    analysis:      工程分析（为什么会有此风险，含力学/工艺机理）
    risk:          风险等级 high / medium / low
    recommendation:修改建议（可执行）
    standard:      依据标准（GB/T / ISO 条文）

引擎职责：注册规则 → 按零件类型评估 → 生成带工程解释的问题条目。
"""

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("knowledge_base.rules")

RISK_LEVEL = {"high": "高风险", "medium": "中风险", "low": "低风险"}

CATEGORY_CN = {
    "manufacturing": "加工工艺",
    "strength": "强度校核",
    "assembly": "装配配合",
    "standards": "标准符合性",
    "materials": "材料选型",
}

CATEGORY_ORDER = ["strength", "manufacturing", "assembly", "materials", "standards"]

# 零件适用性：None 表示所有类型
_PART_KEYS = {"bolt", "shaft", "flange", "gear"}


@dataclass
class Rule:
    """一条决策规则。condition 返回 True 触发；None 表示不适用（跳过）。

    四段式解释输出（问题/原因/风险/建议）：
        problem        问题：轴肩圆角过小
        cause          原因：应力集中（力学机理）
        consequence    风险：疲劳寿命降低（对产品的实际影响）
        recommendation 建议：增加 R3 圆角
    """
    id: str
    category: str                        # manufacturing/strength/assembly/standards/materials
    name: str                            # 规则名（问题项）
    condition: Callable[[dict], bool | None]   # (params) -> bool|None
    analysis: str                        # 工程解释（量化机理）
    risk: str                            # high/medium/low
    recommendation: str                  # 修改建议
    cause: str = ""                      # 原因（为什么产生此问题）
    consequence: str = ""                # 风险（若不修改对产品的影响）
    standard: str = ""                   # 依据标准
    level: str = "warning"               # error/warning/info（风险等级衍生展示级别）
    applies_to: list[str] | None = None  # 适用零件；None=全部
    needs_torque: bool = False           # 需要扭矩参数（默认无载荷信息时转 info）

    def applicable(self, part_type: str) -> bool:
        return self.applies_to is None or part_type in self.applies_to

    def to_issue(self, part_type: str) -> dict:
        """转换为统一问题条目（四段式解释 + 兼容原字段）。"""
        return {
            "level": self.level,
            "item": f"[{CATEGORY_CN.get(self.category, self.category)}] {self.name}",
            "detail": self.analysis,
            "suggestion": self.recommendation,
            "category": self.category,
            "category_cn": CATEGORY_CN.get(self.category, self.category),
            "risk": self.risk,
            "risk_cn": RISK_LEVEL.get(self.risk, self.risk),
            "analysis": self.analysis,
            "recommendation": self.recommendation,
            "standard": self.standard,
            # 四段式解释字段
            "problem": self.name,
            "cause": self.cause or self.analysis,
            "consequence": self.consequence,
        }


# 注册表：按类别分组
RULES: dict[str, list[Rule]] = {cat: [] for cat in CATEGORY_ORDER}
_loaded = False


def register(rule: Rule):
    if rule.category not in RULES:
        RULES[rule.category] = []
    RULES[rule.category].append(rule)


def load_rules() -> list[Rule]:
    """导入规则数据（延迟加载，幂等）。"""
    global _loaded
    if not _loaded:
        from knowledge_base import rules_data  # noqa: F401
        _loaded = True
    return [r for cat in CATEGORY_ORDER for r in RULES.get(cat, [])]


def evaluate(part_type: str, params: dict, torque_nm: float | None = None) -> list[dict]:
    """按零件类型评估全部规则，返回问题条目（已按类别排序）。"""
    load_rules()
    p = dict(params or {})
    p = dict(params or {})
    if torque_nm is not None:
        p["_torque_nm"] = float(torque_nm)
    issues = []
    for category in CATEGORY_ORDER:
        for rule in RULES.get(category, []):
            if not rule.applicable(part_type):
                continue
            try:
                # 需要扭矩但未提供 → 跳过（避免误导）
                if rule.needs_torque and torque_nm is None:
                    continue
                triggered = rule.condition(p)
                if not triggered:
                    continue
                issues.append(rule.to_issue(part_type))
            except Exception:
                log.exception("规则 %s 评估异常", rule.id)
    return issues


def load_rules() -> list[Rule]:
    """导入规则数据（延迟加载避免循环依赖）。"""
    from knowledge_base import rules_data  # noqa: F401
    return [r for cat in CATEGORY_ORDER for r in RULES.get(cat, [])]


def summary() -> dict:
    """规则库概览（文档/演示用）。"""
    load_rules()
    out = {}
    for cat in CATEGORY_ORDER:
        out[cat] = {
            "name": CATEGORY_CN[cat],
            "count": len(RULES.get(cat, [])),
            "rules": [{"id": r.id, "name": r.name, "standard": r.standard,
                       "risk": r.risk, "level": r.level,
                       "applies_to": r.applies_to or list(_PART_KEYS)}
                      for r in RULES.get(cat, [])],
        }
    return out
