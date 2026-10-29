"""Regression tests for inspection helpers that do not require FreeCAD."""

from inspection import manufacturability_checker


def test_manufacturability_accepts_precomputed_features():
    """Passing detected features must not leave feature_detector undefined."""
    parsed = {
        "fillets": [{"r": 0.2, "location": [0, 0, 0]}],
        "bbox_center": [0, 0, 0],
        "wall_thickness": [],
        "holes": [],
        "concave_corners": [],
    }
    issues = manufacturability_checker.check(parsed, features=[])
    assert any("R0.2" in issue["feature"] for issue in issues)


def test_manufacturability_detects_features_when_not_supplied():
    parsed = {
        "fillets": [{"r": 0.2, "location": [0, 0, 0]}],
        "bbox_center": [0, 0, 0],
        "wall_thickness": [],
        "holes": [],
        "concave_corners": [],
    }
    issues = manufacturability_checker.check(parsed)
    assert any("R0.2" in issue["feature"] for issue in issues)
