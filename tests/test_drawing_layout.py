"""Drawing layout must scale safely without part-length special cases."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "freecad_addon"))

from AICADCopilot.drawing.layout_engine import DrawingLayoutEngine  # noqa: E402
from AICADCopilot.drawing.rule_engine import MechanicalDrawingRuleEngine  # noqa: E402
from AICADCopilot.drawing.validator import DrawingValidator  # noqa: E402


def _dimensions(length):
    segments = (length * 0.25, length * 0.5, length * 0.25)
    return [
        {"role": "overall_length", "value": length, "text": f"{length:g}"},
        *[
        {"role": f"shoulder_location_{index + 1}", "value": sum(segments[:index + 1]),
             "text": f"{sum(segments[:index + 1]):g}", "start_fraction": 0.0,
             "end_fraction": sum(segments[:index + 1]) / length}
            for index, value in enumerate(segments[:-1])
        ],
        {"role": "diameter_1", "value": 30.0, "text": "Ø30"},
        {"role": "diameter_2", "value": 40.0, "text": "Ø40"},
        {"role": "chamfer", "value": 1.0, "text": "C1"},
        {"role": "radius", "value": 1.25, "text": "R1.25"},
    ]


def test_shaft_lengths_choose_standard_scale_and_validate():
    expected = {150.0: "1:1", 300.0: "1:2", 500.0: "1:2.5"}
    for length, label in expected.items():
        dimensions = _dimensions(length)
        spec = {"part_type": "shaft", "total_length_mm": length,
                "segments": [
                    {"diameter_mm": 30, "length_mm": length * .25},
                    {"diameter_mm": 40, "length_mm": length * .5},
                    {"diameter_mm": 30, "length_mm": length * .25},
                ],
                "features": [{"type": "chamfer"}, {"type": "fillet"}]}
        strategy = MechanicalDrawingRuleEngine().select_required_views(spec, [])
        layout = DrawingLayoutEngine().layout(
            {"x_length": 40.0, "y_length": 40.0, "z_length": length},
            dimensions,
            [{"role": "manufacturing_notes", "text": "Material: 45 steel"}],
            strategy=strategy,
        )
        validation = DrawingValidator().validate(
            layout, [item["role"] for item in dimensions])
        assert layout["scale_label"] == label
        assert set(layout["views"]) == {"front", "end"}
        assert layout["views"]["end"]["bbox"].right < layout["views"]["front"]["bbox"].left
        assert layout["views"]["end"]["bbox"].center_y == layout["views"]["front"]["bbox"].center_y
        assert validation == {
            **validation,
            "inside_border": True,
            "standard_scale": True,
            "dimension_overlap": False,
            "view_overlap": False,
            "title_block_overlap": False,
            "required_dimensions_present": True,
            "associative_dimensions": True,
            "annotation_overlap": False,
            "projection_consistent": True,
            "centerlines_present": True,
            "view_count_minimal": True,
            "view_count_sufficient": True,
            "dimension_chain_valid": True,
            "duplicate_dimensions": False,
            "manufacturing_dimensions_complete": True,
            "functional_tolerances_justified": True,
            "isometric_view_justified": True,
            "section_view_justified": True,
            "line_types_valid": True,
            "title_block_complete": True,
            "drawing_standard_declared": True,
            "geometry_layout": "PASS",
            "mechanical_representation": "PASS",
            "dimensioning": "PASS",
            "tolerancing": "PASS",
            "manufacturing_completeness": "PASS",
            "passed": True,
        }


def test_validator_fails_when_dimension_leaves_safe_area():
    dimensions = _dimensions(300.0)
    layout = DrawingLayoutEngine().layout(
        {"x_length": 40.0, "y_length": 40.0, "z_length": 300.0}, dimensions,
        strategy=MechanicalDrawingRuleEngine().select_required_views({
            "part_type": "shaft", "total_length_mm": 300,
            "segments": [{"diameter_mm": 30, "length_mm": 75},
                         {"diameter_mm": 40, "length_mm": 150},
                         {"diameter_mm": 30, "length_mm": 75}],
            "features": [{"type": "chamfer"}, {"type": "fillet"}]}, []))
    layout["dimensions"][0]["bbox"] = layout["dimensions"][0]["bbox"].moved(dx=-500.0)
    validation = DrawingValidator().validate(
        layout, [item["role"] for item in dimensions])
    assert validation["inside_border"] is False
    assert validation["passed"] is False


def test_no_length_specific_recipe_branch_exists():
    source = (ROOT / "freecad_addon" / "AICADCopilot" / "drawing" /
              "layout_engine.py").read_text(encoding="utf-8")
    assert "length == 300" not in source
    assert "2.85714" not in source
