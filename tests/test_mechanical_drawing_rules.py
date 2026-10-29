"""Mechanical drawing strategy differs by part and rejects template guesses."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "freecad_addon"))

from AICADCopilot.drawing.rule_engine import select_required_views  # noqa: E402


def test_shaft_uses_minimal_first_angle_views_and_open_dimension_scheme():
    strategy = select_required_views({
        "part_type": "shaft", "total_length_mm": 300,
        "segments": [{"diameter_mm": 30, "length_mm": 75},
                     {"diameter_mm": 40, "length_mm": 150},
                     {"diameter_mm": 30, "length_mm": 75}],
        "features": [{"type": "chamfer"}, {"type": "fillet"}],
    }, [])
    assert strategy["projection_method"] == "first_angle"
    assert strategy["required_view_roles"] == ["front", "end"]
    assert "axonometric" not in strategy["why_this_view_exists"]
    assert strategy["dimensions"] == [
        "overall_length", "shoulder_location_1", "shoulder_location_2",
        "diameter_1", "diameter_2", "chamfer", "radius",
    ]
    assert strategy["dimension_chain_valid"] is True


def test_part_strategies_are_not_one_fixed_template():
    flange = select_required_views({"part_type": "flange", "parameters": {
        "D": 160, "d": 60, "t": 20, "n": 8, "pcd": 120, "hole_d": 14}}, [])
    plate = select_required_views({"part_type": "plate", "parameters": {
        "length": 120, "width": 80, "thickness": 10, "hole_d": 12}}, [])
    assert [v["role"] for v in flange["views"]] == ["front", "side"]
    assert flange["views"][1]["relation"] == "left_of_primary"
    assert [v["role"] for v in plate["views"]] == ["front", "side"]
    assert plate["views"][1]["relation"] == "below_primary"
    assert flange["dimensions"] != plate["dimensions"]


def test_tolerance_and_surface_guesses_are_not_promoted_to_requirements():
    strategy = select_required_views({
        "part_type": "shaft", "total_length_mm": 100,
        "segments": [{"diameter_mm": 20, "length_mm": 100}],
        "tolerances": [{"dimension": "diameter_1", "value": "h6",
                        "source": {"kind": "assumption", "detail": "template"}}],
        "surface_requirements": [{"value": "Ra 3.2",
                                  "source": {"kind": "assumption", "detail": "template"}}],
    }, [])
    assert strategy["tolerances"] == []
    assert strategy["functional_tolerances_justified"] is False
    assert strategy["surface_requirements"] == []
    assert strategy["surface_recommendations"][0]["value"] == "Ra 3.2"
