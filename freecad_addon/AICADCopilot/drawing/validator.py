"""Mechanical and geometric validation gate for generated TechDraw pages."""

from __future__ import annotations

from AICADCopilot.drawing.layout_engine import STANDARD_SCALES


class DrawingValidator:
    def __init__(self, gap=1.5):
        self.gap = float(gap)

    @staticmethod
    def _pairs(items):
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                yield first, second

    @staticmethod
    def _projection_consistent(views):
        primary = views.get("front")
        if not primary:
            return False
        front = primary["bbox"]
        for role, item in views.items():
            if role == "front":
                continue
            rect = item["bbox"]
            relation = str(item.get("relation") or "auxiliary")
            if relation == "left_of_primary":
                if rect.right >= front.left or abs(rect.center_y - front.center_y) > 2.0:
                    return False
            elif relation == "below_primary":
                if rect.top >= front.bottom or abs(rect.center_x - front.center_x) > 2.0:
                    return False
        return True

    def validate(self, layout, required_dimensions=None, associative=None, evidence=None):
        evidence = dict(evidence or {})
        strategy = dict(layout.get("strategy") or {})
        safe = layout["safe_drawing_bounds"]
        border = layout["border_bounds"]
        title = layout["title_block_bounds"]
        notes = layout["notes_bounds"]
        views_by_role = dict(layout["views"])
        views = list(views_by_role.values())
        dimensions = list(layout.get("dimensions") or [])
        annotations = list(layout.get("annotations") or [])

        drawing_rects = [item["bbox"] for item in views + dimensions]
        inside_border = all(border.contains(rect) and safe.contains(rect)
                            for rect in drawing_rects)
        inside_border = inside_border and all(notes.contains(item["bbox"])
                                              for item in annotations)
        dimension_overlap = any(first["bbox"].intersects(second["bbox"], self.gap)
                                for first, second in self._pairs(dimensions))
        dimension_view_overlap = any(dim["bbox"].intersects(view["bbox"], 0.5)
                                     for dim in dimensions for view in views)
        view_overlap = any(first["bbox"].intersects(second["bbox"], self.gap)
                           for first, second in self._pairs(views))
        title_overlap = any(title.intersects(rect) for rect in drawing_rects)
        title_overlap = title_overlap or any(title.intersects(item["bbox"])
                                             for item in annotations)
        annotation_overlap = any(first["bbox"].intersects(second["bbox"], 0.5)
                                 for first, second in self._pairs(annotations))

        actual_roles = {str(item.get("role")) for item in dimensions}
        required = set(required_dimensions or strategy.get("dimensions") or [])
        required_present = required.issubset(actual_roles)
        associative_map = associative or {role: True for role in actual_roles}
        associative_dimensions = bool(actual_roles) and all(
            bool(associative_map.get(role, False)) for role in actual_roles)
        standard_scale = any(abs(float(layout["scale"]) - value) < 1e-9
                             for value in STANDARD_SCALES)

        required_views = set(strategy.get("required_view_roles") or views_by_role)
        optional_views = set(strategy.get("optional_view_roles") or [])
        actual_views = set(views_by_role)
        view_count_sufficient = required_views.issubset(actual_views)
        view_count_minimal = actual_views.issubset(required_views | optional_views)
        projection_consistent = self._projection_consistent(views_by_role)
        centerlines_present = bool(evidence.get("centerlines_present", True))
        dimension_chain_valid = bool(strategy.get("dimension_chain_valid", True))
        duplicate_dimensions = bool(strategy.get("duplicate_dimensions", False))
        manufacturing_complete = bool(required_present and
                                      evidence.get("manufacturing_dimensions_complete", True))
        tolerance_justified = bool(strategy.get("functional_tolerances_justified", True) and
                                   evidence.get("functional_tolerances_justified", True))
        isometric_present = "axonometric" in actual_views
        isometric_justified = bool(not isometric_present or
                                   strategy.get("isometric_view_justified", False))
        section_present = "section" in actual_views
        section_justified = bool(not section_present or
                                 strategy.get("section_view_justified", False))
        line_types_valid = bool(evidence.get("line_types_valid", True))
        title_complete = bool(evidence.get("title_block_complete", True))
        standard_declared = bool(strategy.get("drawing_standard") and
                                 evidence.get("drawing_standard_declared", True))

        geometry_layout = (inside_border and standard_scale and not dimension_overlap and
                           not dimension_view_overlap and not view_overlap and
                           not title_overlap and not annotation_overlap)
        mechanical_representation = (projection_consistent and centerlines_present and
                                     view_count_minimal and view_count_sufficient and
                                     isometric_justified and section_justified and
                                     line_types_valid and standard_declared)
        dimensioning = (dimension_chain_valid and not duplicate_dimensions and
                        required_present and associative_dimensions)
        tolerancing = tolerance_justified
        manufacturing = manufacturing_complete and title_complete
        passed = all((geometry_layout, mechanical_representation, dimensioning,
                      tolerancing, manufacturing))
        return {
            "inside_border": bool(inside_border),
            "standard_scale": bool(standard_scale),
            "dimension_overlap": bool(dimension_overlap or dimension_view_overlap),
            "view_overlap": bool(view_overlap),
            "title_block_overlap": bool(title_overlap),
            "required_dimensions_present": bool(required_present),
            "associative_dimensions": bool(associative_dimensions),
            "annotation_overlap": bool(annotation_overlap),
            "projection_consistent": bool(projection_consistent),
            "centerlines_present": bool(centerlines_present),
            "view_count_minimal": bool(view_count_minimal),
            "view_count_sufficient": bool(view_count_sufficient),
            "dimension_chain_valid": bool(dimension_chain_valid),
            "duplicate_dimensions": bool(duplicate_dimensions),
            "manufacturing_dimensions_complete": bool(manufacturing_complete),
            "functional_tolerances_justified": bool(tolerance_justified),
            "isometric_view_justified": bool(isometric_justified),
            "section_view_justified": bool(section_justified),
            "line_types_valid": bool(line_types_valid),
            "title_block_complete": bool(title_complete),
            "drawing_standard_declared": bool(standard_declared),
            "geometry_layout": "PASS" if geometry_layout else "FAIL",
            "mechanical_representation": "PASS" if mechanical_representation else "FAIL",
            "dimensioning": "PASS" if dimensioning else "FAIL",
            "tolerancing": "PASS" if tolerancing else "FAIL",
            "manufacturing_completeness": "PASS" if manufacturing else "FAIL",
            "passed": bool(passed),
            "required": sorted(required),
            "present": sorted(actual_roles),
            "required_views": sorted(required_views),
            "present_views": sorted(actual_views),
        }
