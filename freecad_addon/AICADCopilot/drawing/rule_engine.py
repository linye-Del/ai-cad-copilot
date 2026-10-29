"""Codified mechanical-drawing decisions, independent from page layout.

The rule engine answers *what must be shown*.  It deliberately does not own
page coordinates; :mod:`layout_engine` owns that separate responsibility.
"""

from __future__ import annotations

from copy import deepcopy


FIRST_ANGLE = "first_angle"
DECLARED_STANDARD = "GB/T 4458.1; GB/T 4458.4; GB/T 14692"


def _source_is_justified(source):
    return str((source or {}).get("kind", "")).lower() in {
        "user", "design_engine", "standard", "functional_requirement"
    }


class MechanicalDrawingRuleEngine:
    """Select the minimum sufficient views and manufacturing information."""

    def select_required_views(self, part_spec, feature_tree=None):
        spec = deepcopy(part_spec or {})
        feature_tree = list(feature_tree or [])
        part_type = str(spec.get("part_type") or "shaft").lower()
        parameters = dict(spec.get("parameters") or {})
        features = list(spec.get("features") or [])
        feature_names = " ".join(
            str(item.get("name") or item.get("label") or item.get("type_id") or "")
            if isinstance(item, dict) else str(item) for item in feature_tree
        ).casefold()
        requested_iso = bool(spec.get("drawing", {}).get("isometric", False))
        requested_section = bool(spec.get("drawing", {}).get("section", False))

        if part_type == "shaft":
            strategy = self._shaft(spec, features, feature_names)
        elif part_type == "flange":
            strategy = self._flange(spec, parameters)
        elif part_type == "plate":
            strategy = self._plate(spec, parameters)
        elif part_type == "bolt":
            strategy = self._bolt(spec, parameters)
        else:
            strategy = self._generic(spec)

        if requested_section and not any(v["role"] == "section" for v in strategy["views"]):
            strategy["views"].append({
                "role": "section", "direction": [1.0, 0.0, 0.0],
                "relation": "left_of_primary", "centerlines": ["horizontal"],
                "reason": "User explicitly requested a section view",
                "required": True,
            })
            strategy["section_view_justified"] = True
        if requested_iso:
            strategy["views"].append({
                "role": "axonometric", "direction": [1.0, -1.0, 1.0],
                "relation": "auxiliary", "centerlines": [],
                "reason": "User explicitly requested an auxiliary axonometric view",
                "required": False,
            })
            strategy["isometric_view_justified"] = True

        strategy.update({
            "part_type": part_type,
            "projection_method": FIRST_ANGLE,
            "drawing_standard": DECLARED_STANDARD,
            "why_this_view_exists": {
                view["role"]: view["reason"] for view in strategy["views"]
            },
        })
        strategy["layout_hint"] = self._layout_hint(part_type, spec, parameters)
        strategy["required_view_roles"] = [
            item["role"] for item in strategy["views"] if item.get("required", True)
        ]
        strategy["optional_view_roles"] = [
            item["role"] for item in strategy["views"] if not item.get("required", True)
        ]
        return strategy

    @staticmethod
    def _layout_hint(part_type, spec, parameters):
        if part_type == "shaft":
            segments = list(spec.get("segments") or [])
            length = float(spec.get("total_length_mm") or
                           sum(float(item.get("length_mm", item.get("length", 0.0)))
                               for item in segments))
            diameter = max([float(item.get("diameter_mm", item.get("diameter", 0.0)))
                            for item in segments] or [1.0])
            return {"primary_width": length, "primary_height": diameter,
                    "auxiliary_width": diameter, "auxiliary_height": diameter}
        if part_type == "flange":
            diameter = float(parameters.get("D", 1.0))
            thickness = float(parameters.get("t", 1.0))
            return {"primary_width": diameter, "primary_height": diameter,
                    "auxiliary_width": thickness, "auxiliary_height": diameter}
        if part_type == "plate":
            length = float(parameters.get("length", 1.0))
            width = float(parameters.get("width", 1.0))
            thickness = float(parameters.get("thickness", 1.0))
            return {"primary_width": length, "primary_height": width,
                    "auxiliary_width": length, "auxiliary_height": thickness}
        if part_type == "bolt":
            diameter = float(parameters.get("s", parameters.get("d", 1.0)))
            length = float(parameters.get("L", 1.0)) + float(parameters.get("k", 0.0))
            return {"primary_width": length, "primary_height": diameter,
                    "auxiliary_width": diameter, "auxiliary_height": diameter}
        return {}

    def _base(self):
        return {
            "views": [],
            "dimensions": [],
            "tolerances": [],
            "surface_requirements": [],
            "surface_recommendations": [],
            "dimension_chain_valid": True,
            "duplicate_dimensions": False,
            "functional_tolerances_justified": True,
            "isometric_view_justified": False,
            "section_view_justified": False,
            "line_types": {
                "visible": "continuous_thick",
                "hidden": "dashed_thin_when_required",
                "center": "chain_thin",
                "dimension": "continuous_thin",
            },
            "general_tolerance": None,
        }

    def _shaft(self, spec, features, feature_names):
        result = self._base()
        has_keyway = ("key" in feature_names or "键槽" in feature_names or
                      any(str(item.get("type", "")).lower() == "keyway"
                          for item in features if isinstance(item, dict)))
        result["views"] = [
            {"role": "front", "direction": [1.0, 0.0, 0.0],
             "relation": "primary", "centerlines": ["horizontal_axis"],
             "reason": "Required to express axial steps, lengths, shoulders and end finishes",
             "required": True},
            {"role": "end", "direction": [0.0, 0.0, 1.0],
             "relation": "left_of_primary", "centerlines": ["horizontal", "vertical", "arc_centers"],
             "reason": ("Required to express the keyway and circular cross-section" if has_keyway
                        else "Required to confirm the circular stepped cross-section"),
             "required": True},
        ]
        segments = list(spec.get("segments") or [])
        result["dimensions"] = ["overall_length"]
        if len(segments) >= 2:
            # Baseline shoulder locations avoid the old 300 + 150 + 2x75
            # closed/redundant chain.  The final shoulder is located from the
            # same left datum, while overall length controls the cut length.
            result["dimensions"].extend(
                "shoulder_location_%d" % index for index in range(1, len(segments))
            )
        unique_diameters = []
        for segment in segments:
            value = float(segment.get("diameter_mm", segment.get("diameter", 0.0)))
            if value > 0 and not any(abs(value - old) < 0.01 for old in unique_diameters):
                unique_diameters.append(value)
        result["dimensions"].extend(
            "diameter_%d" % (index + 1) for index in range(len(unique_diameters))
        )
        if any(str(item.get("type", "")).lower() == "chamfer"
               for item in features if isinstance(item, dict)):
            result["dimensions"].append("chamfer")
        if any(str(item.get("type", "")).lower() == "fillet"
               for item in features if isinstance(item, dict)):
            result["dimensions"].append("radius")
        if has_keyway:
            result["dimensions"].extend(["keyway_width", "keyway_depth", "keyway_length", "keyway_location"])
        self._collect_requirements(spec, result)
        return result

    def _flange(self, spec, p):
        result = self._base()
        result["views"] = [
            {"role": "front", "direction": [0.0, 0.0, 1.0],
             "relation": "primary", "centerlines": ["horizontal", "vertical", "arc_centers"],
             "reason": "Required to express bore, bolt-hole pattern, hole count and PCD",
             "required": True},
            {"role": "side", "direction": [1.0, 0.0, 0.0],
             "relation": "left_of_primary", "centerlines": ["horizontal"],
             "reason": "Required to express flange thickness and axial form",
             "required": True},
        ]
        result["dimensions"] = ["outer_diameter", "bore_diameter", "thickness",
                                "bolt_hole_diameter", "pitch_circle_diameter"]
        result["section_view_justified"] = False
        self._collect_requirements(spec, result)
        return result

    def _plate(self, spec, p):
        result = self._base()
        result["views"] = [
            {"role": "front", "direction": [0.0, 0.0, 1.0],
             "relation": "primary", "centerlines": ["hole_centers"],
             "reason": "Required to express plate outline, hole diameters and hole locations",
             "required": True},
            {"role": "side", "direction": [0.0, 1.0, 0.0],
             "relation": "below_primary", "centerlines": [],
             "reason": "Required because plate thickness is not visible in the primary face view",
             "required": True},
        ]
        result["dimensions"] = ["plate_length", "plate_width", "thickness",
                                "hole_diameter", "hole_pitch_x", "hole_pitch_y"]
        self._collect_requirements(spec, result)
        return result

    def _bolt(self, spec, p):
        result = self._base()
        result["views"] = [
            {"role": "front", "direction": [1.0, 0.0, 0.0],
             "relation": "primary", "centerlines": ["horizontal_axis"],
             "reason": "Required for bolt length, threaded length, shank and head height",
             "required": True},
            {"role": "end", "direction": [0.0, 0.0, 1.0],
             "relation": "left_of_primary", "centerlines": ["horizontal", "vertical"],
             "reason": "Required for the hexagonal head across-flats dimension",
             "required": True},
        ]
        result["dimensions"] = ["thread_designation", "bolt_length", "threaded_length",
                                "across_flats", "head_height", "chamfer"]
        result["thread_representation"] = "simplified; no helical curve as drawing convention"
        self._collect_requirements(spec, result)
        return result

    def _generic(self, spec):
        result = self._base()
        result["views"] = [{
            "role": "front", "direction": [1.0, 0.0, 0.0],
            "relation": "primary", "centerlines": [],
            "reason": "Primary view required to identify the part envelope", "required": True,
        }]
        self._collect_requirements(spec, result)
        return result

    def _collect_requirements(self, spec, result):
        for item in list(spec.get("tolerances") or []):
            if _source_is_justified(item.get("source")):
                result["tolerances"].append(item)
            else:
                result["functional_tolerances_justified"] = False
        general = spec.get("general_tolerance")
        if general and _source_is_justified(general.get("source")):
            result["general_tolerance"] = general
        for item in list(spec.get("surface_requirements") or []):
            if _source_is_justified(item.get("source")):
                result["surface_requirements"].append(item)
            else:
                result["surface_recommendations"].append(item)


def select_required_views(part_spec, feature_tree=None):
    """Public functional entry point required by the Agent planning layer."""
    return MechanicalDrawingRuleEngine().select_required_views(part_spec, feature_tree)
