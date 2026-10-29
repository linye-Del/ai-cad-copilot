"""SVG 工程图生成器单元测试（无需 FreeCAD）。"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cad_engine import drawing_svg as ds


def _specs():
    return [
        {"part_type": "bolt", "part_name": "M10x40六角头螺栓",
         "params": {"d": 10, "L": 40, "b": 25, "s": 16, "k": 6.4, "material": "40Cr"}},
        {"part_type": "shaft", "part_name": "三阶阶梯轴",
         "params": {"segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
                    "material": "45钢"}},
        {"part_type": "flange", "part_name": "法兰盘D160",
         "params": {"D": 160, "d": 50, "t": 18, "n": 8, "pcd": 130, "hole_d": 11}},
        {"part_type": "gear", "part_name": "直齿圆柱齿轮",
         "params": {"m": 2.5, "z": 20, "b": 25, "d_hub": 30}},
    ]


def test_all_parts_render_valid_xml():
    """4 种零件 SVG 均为合法 XML。"""
    for spec in _specs():
        svg = ds.render(spec)
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")


def test_drawing_contains_dimensions():
    """工程图含尺寸标注（红色 dim 样式）。"""
    svg = ds.render(_specs()[0])
    assert 'stroke:#c00' in svg  # 尺寸线红色
    assert "L=40" in svg         # 总长标注


def test_title_block_contains_part_name():
    """标题栏含零件名。"""
    svg = ds.render(_specs()[1])
    assert "三阶阶梯轴" in svg


def test_bolt_dimensions_labeled():
    """螺栓尺寸标注齐全。"""
    svg = ds.render(_specs()[0])
    for label in ("d=10", "L=40", "b=25"):
        assert label in svg, f"缺少标注 {label}"


def test_unsupported_type_raises():
    """不支持的类型抛错。"""
    import pytest
    with pytest.raises(ValueError):
        ds.render({"part_type": "unknown", "params": {}})
