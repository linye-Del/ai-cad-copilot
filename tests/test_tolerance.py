"""工程图公差检查单元测试（无需 FreeCAD）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inspection import tolerance_check as tc


def _shaft():
    return {"segments": [{"d": 45, "L": 80}, {"d": 45, "L": 45},
                         {"d": 50, "L": 70}, {"d": 45, "L": 45}, {"d": 45, "L": 60}],
            "keyway": {"enabled": True, "seg_index": 0, "w": 14, "t": 5.5, "lk": 63}}


def test_missing_tolerance_detected():
    """关键位置缺标 → 建议（含标准依据）。"""
    issues = tc.check_tolerances("shaft", _shaft())
    suggestions = [i["suggestion"] for i in issues]
    assert any("轴承" in s for s in suggestions)
    assert any("k6" in s for s in suggestions)  # 轴承位建议 k6
    assert any("JS9" in s for s in suggestions)  # 键槽宽度建议 JS9
    assert all(i["standard"] for i in issues)    # 每条有标准依据


def test_gear_hub_recommendation():
    """齿轮毂孔建议 H7。"""
    issues = tc.check_tolerances("gear", {"m": 2.5, "z": 20, "b": 25, "d_hub": 30})
    assert any("H7" in i["suggestion"] for i in issues)


def test_clearance_fit_rejected_for_bearing():
    """轴承位误用间隙配合 → warning。"""
    p = _shaft()
    p["tolerances"] = [{"feature": "bearing_seat", "fit": "H7/g6"}]
    issues = tc.validate_provided("shaft", p)
    assert any(i["level"] == "warning" and "间隙" in i["detail"] for i in issues)


def test_full_correct_tolerances_pass():
    """完整正确标注 → 无 warning。"""
    p = _shaft()
    p["tolerances"] = [
        {"feature": "bearing_seat", "fit": "k6"},
        {"feature": "journal", "it": "IT6"},
        {"feature": "keyway_width", "fit": "JS9"},
        {"feature": "keyway_symmetry", "fit": "对称度8级"},
    ]
    issues = tc.check_tolerances("shaft", p)
    assert not any(i["level"] in ("error", "warning") for i in issues)


def test_fit_type_lookup():
    """配合类别查询。"""
    from knowledge_base import gbt
    assert gbt.fit_type("H7/g6") == "clearance"
    assert gbt.fit_type("H7/k6") == "transition"
    assert gbt.fit_type("H7/p6") == "interference"
    assert gbt.fit_type("XX/zz") == "unknown"
