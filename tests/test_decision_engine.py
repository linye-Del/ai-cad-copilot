"""Engineering Decision Engine 单元测试（无需 FreeCAD）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge_base import decision_engine as de


def test_high_risk_small_shaft():
    """500Nm + d30：高风险，建议增加轴径至 45mm。"""
    r = de.analyze_shaft(500, 30, 300, "45钢")
    assert r["risk"] == "高风险"
    assert r["design"]["safety_factor"] < 1.0
    assert r["design"]["recommend_d_range_mm"][0] >= 45
    assert "45mm" in r["recommendation"]
    assert r["design"]["tau_actual_mpa"] > r["design"]["tau_allow_mpa"]


def test_recommended_diameter_low_risk():
    """500Nm + d55：低风险（n ≥ 1.5）。"""
    r = de.analyze_shaft(500, 55, 300, "45钢")
    assert r["risk"] == "低风险"
    assert r["design"]["safety_factor"] >= 1.5


def test_material_affects_risk():
    """同轴径换材料：40Cr 比 45钢 安全系数高。"""
    r1 = de.analyze_shaft(500, 40, 300, "45钢")
    r2 = de.analyze_shaft(500, 40, 300, "40Cr")
    assert r2["design"]["safety_factor"] > r1["design"]["safety_factor"]


def test_material_recommendation_by_load():
    """载荷分级材料建议。"""
    assert "Q235" in de.recommend_material(50)
    assert "45钢" in de.recommend_material(300)
    assert "40Cr" in de.recommend_material(1000)
    assert "35CrMo" in de.recommend_material(5000)


def test_five_field_format():
    """输出包含五字段规则格式。"""
    r = de.analyze_shaft(500, 30, 300, "45钢")
    for field in ("condition", "analysis", "risk", "recommendation", "standard"):
        assert field in r, f"缺少字段 {field}"
        assert r[field], f"字段为空 {field}"


def test_evaluate_design_integration():
    """设计总评估：参数合理性 + 工艺 + 装配 + 标准。"""
    params = {"segments": [{"d": 30, "L": 80}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
              "chamfer": 1.0, "material": "45钢"}
    r = de.evaluate_design("shaft", params, torque_nm=500)
    assert "shaft_analysis" in r
    assert r["shaft_analysis"]["risk"] == "高风险"
    assert r["rules_count"] > 0
    assert "categories" in r and r["categories"]
