"""Deterministic TechDraw page layout without part-recipe coordinates."""

from __future__ import annotations

from dataclasses import dataclass


STANDARD_SCALES = (2.0, 1.0, 0.5, 0.4, 0.2, 0.1)


@dataclass(frozen=True)
class Rect:
    left: float
    bottom: float
    right: float
    top: float

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.top - self.bottom

    @property
    def center_x(self):
        return (self.left + self.right) / 2.0

    @property
    def center_y(self):
        return (self.bottom + self.top) / 2.0

    def contains(self, other, margin=0.0):
        return (other.left >= self.left + margin and
                other.right <= self.right - margin and
                other.bottom >= self.bottom + margin and
                other.top <= self.top - margin)

    def intersects(self, other, gap=0.0):
        return not (self.right + gap <= other.left or
                    other.right + gap <= self.left or
                    self.top + gap <= other.bottom or
                    other.top + gap <= self.bottom)

    def moved(self, dx=0.0, dy=0.0):
        return Rect(self.left + dx, self.bottom + dy,
                    self.right + dx, self.top + dy)

    def as_dict(self):
        return {"left": round(self.left, 3), "bottom": round(self.bottom, 3),
                "right": round(self.right, 3), "top": round(self.top, 3),
                "width": round(self.width, 3), "height": round(self.height, 3)}


PAGE_FORMATS = {
    "A4_LANDSCAPE": {
        "width": 297.0, "height": 210.0,
        "border": Rect(20.0, 10.0, 287.0, 200.0),
        # Measured from the bundled ISO5457 advanced SVG template.  Its title
        # block begins near X=107, not X=167 as the old guessed rectangle did.
        "title_block": Rect(107.0, 10.0, 287.0, 65.0),
        "notes": Rect(20.0, 10.0, 102.0, 62.0),
        "safe": Rect(25.0, 70.0, 282.0, 195.0),
    },
    "A3_LANDSCAPE": {
        "width": 420.0, "height": 297.0,
        "border": Rect(20.0, 10.0, 410.0, 287.0),
        "title_block": Rect(230.0, 10.0, 410.0, 65.0),
        "notes": Rect(20.0, 10.0, 225.0, 62.0),
        "safe": Rect(25.0, 70.0, 405.0, 282.0),
    },
}


def format_scale(scale):
    if scale >= 1.0:
        return "%g:1" % scale
    return "1:%g" % (1.0 / scale)


def _bbox(center_x, center_y, width, height):
    return Rect(center_x - width / 2.0, center_y - height / 2.0,
                center_x + width / 2.0, center_y + height / 2.0)


class DrawingLayoutEngine:
    """Select a standard scale and place views/dimension text in safe zones."""

    def __init__(self, max_iterations=8, object_gap=3.0):
        self.max_iterations = max(1, min(int(max_iterations), 20))
        self.object_gap = float(object_gap)

    def layout(self, model_bbox, dimensions, annotations=None, preferred_page="A4_LANDSCAPE",
               strategy=None):
        strategy = dict(strategy or {})
        extents = sorted([abs(float(model_bbox.get(key, 0.0)))
                          for key in ("x_length", "y_length", "z_length")], reverse=True)
        hint = dict(strategy.get("layout_hint") or {})
        primary_width = float(hint.get("primary_width") or (extents[0] if extents else 0.0))
        primary_height = float(hint.get("primary_height") or
                               (extents[1] if len(extents) > 1 else 0.0))
        if primary_width <= 0.0 or primary_height <= 0.0:
            raise ValueError("Model bounding box must contain positive extents")
        page_order = [preferred_page] + [name for name in PAGE_FORMATS if name != preferred_page]
        for page_name in page_order:
            page = PAGE_FORMATS[page_name]
            safe = page["safe"]
            for scale in STANDARD_SCALES:
                # Main view has priority.  Reserve margins for extension lines,
                # while auxiliary views occupy a separate lower row.
                auxiliary = next((view for view in strategy.get("views", [])
                                  if view.get("role") != "front"), None)
                relation = str((auxiliary or {}).get("relation") or "")
                aux_width = float(hint.get("auxiliary_width") or primary_height)
                aux_height = float(hint.get("auxiliary_height") or primary_height)
                horizontal_reserve = (aux_width * scale + 12.0
                                      if relation == "left_of_primary" else 0.0)
                vertical_reserve = (aux_height * scale + 18.0
                                    if relation == "below_primary" else 0.0)
                if primary_width * scale + 24.0 + horizontal_reserve > safe.width:
                    continue
                if primary_height * scale + 48.0 + vertical_reserve > safe.height:
                    continue
                candidate = self._build(page_name, page, primary_width, primary_height, scale,
                                        list(dimensions or []), list(annotations or []),
                                        strategy)
                if self._resolve(candidate):
                    return candidate
        raise RuntimeError("No standard page/scale can contain the drawing safely")

    def _build(self, page_name, page, length, diameter, scale, dimensions, annotations,
               strategy):
        safe = page["safe"]
        hint = dict(strategy.get("layout_hint") or {})
        view_specs = list(strategy.get("views") or [
            {"role": "front", "relation": "primary"},
            {"role": "end", "relation": "left_of_primary"},
        ])
        front_width = length * scale
        front_height = max(6.0, diameter * scale)
        left_aux = next((item for item in view_specs
                         if item.get("relation") == "left_of_primary"), None)
        below_aux = next((item for item in view_specs
                          if item.get("relation") == "below_primary"), None)
        aux_width = max(8.0, float(hint.get("auxiliary_width") or diameter) * scale)
        aux_height = max(8.0, float(hint.get("auxiliary_height") or diameter) * scale)
        if left_aux:
            available_left = safe.left + aux_width + 18.0
            front_x = available_left + (safe.right - available_left) / 2.0
        else:
            front_x = safe.center_x
        if below_aux:
            available_bottom = safe.bottom + aux_height + 18.0
            front_y = available_bottom + (safe.top - available_bottom) / 2.0
        else:
            front_y = safe.center_y
        front = _bbox(front_x, front_y, front_width, front_height)

        views = {"front": {"x": front_x, "y": front_y, "scale": scale,
                           "bbox": front, "relation": "primary"}}
        for item in view_specs:
            role = str(item.get("role") or "")
            if not role or role == "front":
                continue
            relation = str(item.get("relation") or "auxiliary")
            item_scale = scale
            width, height = aux_width, aux_height
            if role == "axonometric":
                smaller = [value for value in STANDARD_SCALES if value < scale]
                item_scale = smaller[0] if smaller else scale
                width = max(12.0, (length * 0.72 + diameter) * item_scale)
                height = max(12.0, (length * 0.42 + diameter) * item_scale)
            if relation == "left_of_primary":
                center_x = safe.left + width / 2.0 + 5.0
                center_y = front.center_y
            elif relation == "below_primary":
                center_x = front.center_x
                center_y = safe.bottom + height / 2.0 + 5.0
            else:
                center_x = safe.right - width / 2.0 - 5.0
                center_y = safe.bottom + height / 2.0 + 5.0
            rect = _bbox(center_x, center_y, width, height)
            views[role] = {"x": center_x, "y": center_y, "scale": item_scale,
                           "bbox": rect, "relation": relation}

        boundaries = [front.left]
        segment_dims = [item for item in dimensions if item.get("role", "").startswith("segment_length")]
        segment_total = sum(max(0.0, float(item.get("value", 0.0))) for item in segment_dims)
        if segment_total > 0.0:
            cursor = front.left
            for item in segment_dims:
                cursor += front_width * float(item.get("value", 0.0)) / segment_total
                boundaries.append(cursor)

        dimension_items = []
        segment_index = 0
        upper_lane = 0
        lower_lane = 0
        diameter_lane = 0
        for item in dimensions:
            role = str(item.get("role") or "dimension")
            value = float(item.get("value", 0.0))
            text = str(item.get("text") or role)
            text_width = max(10.0, min(38.0, 2.25 * len(text) + 4.0))
            text_height = 6.0
            if role == "overall_length":
                x, y = front.center_x, front.top + 18.0
            elif role.startswith("segment_length") or role.startswith("shoulder_location"):
                if "start_fraction" in item and "end_fraction" in item:
                    x = front.left + front.width * (
                        float(item["start_fraction"]) + float(item["end_fraction"])) / 2.0
                elif segment_index + 1 < len(boundaries):
                    x = (boundaries[segment_index] + boundaries[segment_index + 1]) / 2.0
                else:
                    x = front.center_x
                y = front.bottom - 12.0 - lower_lane * 8.0
                segment_index += 1
            elif role.startswith("diameter"):
                x = front.left + front.width * (0.20 + 0.55 * (diameter_lane % 2))
                y = front.top + 9.0 + (diameter_lane // 2) * 8.0
                diameter_lane += 1
            elif role == "chamfer":
                x, y = front.left + 13.0, front.top + 9.0 + upper_lane * 8.0
                upper_lane += 1
            elif role == "radius":
                # Keep the leader in the same local shoulder zone as the
                # projected fillet edge.  A far-right text position can make
                # FreeCAD choose an equally-sized fillet on the left and draw
                # a leader through the entire shaft.  The one-third station is
                # generic for long-axis parts and remains clear of the C callout
                # at the left end without depending on a specific shaft length.
                x, y = front.left + front.width * 0.35, front.top + 7.0
            elif role.startswith("keyway"):
                x, y = front.center_x, front.bottom - 12.0 - lower_lane * 8.0
                upper_lane += 1
            elif role in {"outer_diameter", "bore_diameter", "bolt_hole_diameter",
                          "pitch_circle_diameter", "hole_diameter"}:
                x = front.right + 13.0 + (upper_lane % 2) * 9.0
                y = front.center_y + (upper_lane - 1) * 9.0
                upper_lane += 1
            elif role in {"plate_length"}:
                x, y = front.center_x, front.top + 12.0
            elif role in {"plate_width"}:
                x, y = front.right + 13.0, front.center_y
            elif role in {"thickness"}:
                auxiliary = next((view for name, view in views.items() if name != "front"), None)
                if auxiliary:
                    x, y = auxiliary["bbox"].center_x, auxiliary["bbox"].bottom - 10.0
                else:
                    x, y = front.center_x, front.bottom - 12.0
            elif role in {"hole_location_x", "hole_pitch_x"}:
                # Keep the horizontal hole-pattern dimension with the primary
                # face view.  Putting it below the view would route extension
                # lines through the separate thickness view.
                x, y = front.center_x, front.top + 22.0
            elif role in {"hole_location_y", "hole_pitch_y"}:
                x, y = front.left - 13.0, front.center_y
            else:
                x, y = front.center_x, front.bottom - 12.0 - lower_lane * 8.0
                lower_lane += 1
            dimension_items.append({**item, "role": role, "value": value,
                                    "x": x, "y": y,
                                    "bbox": _bbox(x, y, text_width, text_height)})

        annotation_items = []
        note_bounds = page["notes"]
        for index, annotation in enumerate(annotations):
            x = note_bounds.center_x
            y = note_bounds.top - 8.0 - index * 8.0
            width = min(note_bounds.width - 10.0,
                        max(30.0, len(str(annotation.get("text", ""))) * 2.0))
            annotation_items.append({**annotation, "x": x, "y": y,
                                     "bbox": _bbox(x, y, width, 6.0)})

        return {
            "page_format": page_name,
            "page_width": page["width"], "page_height": page["height"],
            "page_bounds": Rect(0.0, 0.0, page["width"], page["height"]),
            "border_bounds": page["border"],
            "title_block_bounds": page["title_block"],
            "notes_bounds": note_bounds,
            "safe_drawing_bounds": safe,
            "scale": scale, "scale_label": format_scale(scale),
            "model": {"length": length, "diameter": diameter},
            "views": views,
            "strategy": strategy,
            "dimensions": dimension_items,
            "annotations": annotation_items,
            "iterations": 0,
        }

    def _resolve(self, layout):
        safe = layout["safe_drawing_bounds"]
        views = [item["bbox"] for item in layout["views"].values()]
        placed = []
        for item in layout["dimensions"]:
            rect = item["bbox"]
            origin = rect
            for iteration in range(self.max_iterations):
                collision = any(rect.intersects(other, self.object_gap) for other in placed)
                severe_view_overlap = any(rect.intersects(view, 0.5) for view in views)
                if safe.contains(rect, 0.5) and not collision and not severe_view_overlap:
                    break
                direction = 1.0 if iteration % 2 == 0 else -1.0
                distance = (iteration // 2 + 1) * 8.0
                moved = origin.moved(dy=direction * distance)
                if not safe.contains(moved, 0.5):
                    moved = origin.moved(dx=direction * distance, dy=0.0)
                rect = moved
            else:
                return False
            item["bbox"] = rect
            item["x"], item["y"] = rect.center_x, rect.center_y
            placed.append(rect)
            layout["iterations"] += iteration + 1
        return all(safe.contains(item["bbox"], 0.5) for item in layout["dimensions"])

    @staticmethod
    def serializable(layout):
        result = dict(layout)
        for key in ("page_bounds", "border_bounds", "title_block_bounds",
                    "notes_bounds", "safe_drawing_bounds"):
            result[key] = layout[key].as_dict()
        result["views"] = {name: {**item, "bbox": item["bbox"].as_dict()}
                           for name, item in layout["views"].items()}
        result["dimensions"] = [{**item, "bbox": item["bbox"].as_dict()}
                                for item in layout["dimensions"]]
        result["annotations"] = [{**item, "bbox": item["bbox"].as_dict()}
                                 for item in layout["annotations"]]
        return result
