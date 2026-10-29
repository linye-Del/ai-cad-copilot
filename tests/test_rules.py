"""决策系统规则引擎单元测试（无需 FreeCAD）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inspection import rules as rc


def test_rules_categories():
    """五大类别规则均存在且总数 ≥27。"""
    s = rc.rules_summary()
    assert set(s) == {"strength", "manufacturing", "assembly", "materials", "standards"}
    total = sum(info["count"] for info in s.values())
    assert total >= 27


def test_four_field_explanation():
    """规则输出含四段式解释字段（problem/cause/consequence/recommendation）。"""
    shaft = {"segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
             "chamfer": 1.0, "fillet": 0.0}  # 无圆角 → 触发 mf_fillet_stress
    issues = rc.check("shaft", shaft)
    fillet = [i for i in issues if "圆角" in i.get("item", "")]
    assert fillet, "应触发轴肩圆角规则"
    issue = fillet[0]
    for field in ("problem", "cause", "consequence", "recommendation", "risk", "standard"):
        assert field in issue, f"缺少字段 {field}"
    assert issue["cause"], "原因不能为空"


def test_bolt_basic_check():
    """螺栓硬性错误检查。"""
    issues = rc.check("bolt", {"d": 10, "L": 40})
    assert all(i["level"] != "error" for i in issues)
    # 螺纹长超过杆长 → error
    issues = rc.check("bolt", {"d": 10, "L": 40, "b": 50})
    assert any(i["level"] == "error" for i in issues)


def test_torque_strength_check():
    """扭矩强度校核：弱轴（d30, 500Nm）应触发 error。"""
    weak = {"segments": [{"d": 30, "L": 80}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
            "chamfer": 1.0, "material": "45钢"}
    issues = rc.check("shaft", weak, torque_nm=500)
    assert any(i["level"] == "error" and "扭转" in i["item"] for i in issues)


def test_gear_rim_check():
    """齿轮轮缘厚度规则。"""
    gear = {"m": 2.5, "z": 20, "b": 25, "d_hub": 40}  # 轮缘 (df-40)/2 = 1.875 < 0.8m=2.0
    issues = rc.check("gear", gear)
    assert any("轮缘" in i["item"] for i in issues)


def test_material_rules():
    """材料规则：45钢未热处理、铝合金大扭矩。"""
    shaft = {"segments": [{"d": 45, "L": 80}], "chamfer": 1.0, "material": "45钢"}
    issues = rc.check("shaft", shaft)
    assert any(i.get("category") == "materials" and "热处理" in i["item"] for i in issues)

    al = {"segments": [{"d": 45, "L": 80}], "chamfer": 1.0, "material": "6061铝"}
    issues = rc.check("shaft", al, torque_nm=500)
    assert any("铝合金" in i["item"] for i in issues)


def test_info_does_not_fail_pass():
    """info 级建议不参与 passed 判定。"""
    bolt = {"d": 10, "L": 40}
    issues = rc.check("bolt", bolt)
    assert not any(i["level"] in ("error", "warning") for i in issues)
