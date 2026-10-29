"""Mechanical design policies that produce Live Agent PartSpec objects."""

import math

from agent.live_schema import FeatureSpec, ParameterSource, PartSpec, ShaftSegment
from cad_engine.parts.base import BOLT_STD
from knowledge_base import decision_engine


def _round_to_5(value):
    return max(5.0, math.ceil(float(value) / 5.0) * 5.0)


def design_stepped_shaft(total_length_mm, source_text, torque_nm=None, material="45钢"):
    total = float(total_length_mm)
    if torque_nm is not None:
        minimum = decision_engine.shaft_min_diameter(float(torque_nm), material)
        end_d = _round_to_5(minimum * 1.08)
        source = ParameterSource(
            kind="design_engine",
            detail="Calculated from torsional strength with 1.08 keyway allowance",
        )
        assumptions = []
    else:
        # Concept-design policy when load/interface data is absent.  It scales
        # with the requested length and is reported as an assumption, never as
        # a user-provided or standards-derived dimension.
        end_d = min(80.0, max(20.0, _round_to_5(total / 10.0)))
        source = ParameterSource(
            kind="assumption",
            detail="Concept shaft slenderness policy d≈L/10; load was not supplied",
        )
        assumptions = [
            "未提供扭矩、轴承和联轴器接口；采用概念设计比例 d≈L/10。",
            "轴段按 25% / 50% / 25% 分配，生产设计前必须用真实载荷复核。",
        ]
    middle_d = _round_to_5(end_d * 1.25)
    first_l = round(total * 0.25, 3)
    middle_l = round(total * 0.50, 3)
    last_l = round(total - first_l - middle_l, 3)
    chamfer = min(2.0, max(1.0, end_d / 30.0))
    # Shoulder height is half the diameter difference.  Keep the radius well
    # below that height so the PartDesign fillet remains manufacturable.
    fillet = min(2.0, max(1.0, (middle_d - end_d) / 8.0))
    segments = [
        ShaftSegment(diameter_mm=end_d, length_mm=first_l, source=source),
        ShaftSegment(diameter_mm=middle_d, length_mm=middle_l, source=source),
        ShaftSegment(diameter_mm=end_d, length_mm=last_l, source=source),
    ]
    return PartSpec(
        part_type="shaft",
        name="SteppedShaft_%gmm" % total,
        material=material,
        total_length_mm=total,
        segments=segments,
        features=[
            FeatureSpec(type="chamfer", size_mm=chamfer,
                        source=ParameterSource(kind="design_engine", detail="End-edge machining policy")),
            FeatureSpec(type="fillet", size_mm=fillet,
                        source=ParameterSource(kind="design_engine", detail="Shoulder transition policy")),
        ],
        assumptions=assumptions,
        standards=["GB/T 699", "机械设计手册：轴的结构设计"],
        source_text=source_text,
    )


def design_bolt(diameter_mm, length_mm, source_text, material="40Cr"):
    diameter = float(diameter_mm)
    length = float(length_mm)
    std = BOLT_STD.get(int(round(diameter)))
    if std:
        pitch, across_flats, head_height, _ = std
        source = ParameterSource(kind="standard", detail="GB/T 5782 size table")
    else:
        pitch = max(1.0, round(diameter * 0.15, 2))
        across_flats = _round_to_5(diameter * 1.5)
        head_height = round(diameter * 0.64, 2)
        source = ParameterSource(kind="assumption", detail="Non-table concept proportions")
    return PartSpec(
        part_type="bolt",
        name="M%gx%g_Bolt" % (diameter, length),
        material=material,
        total_length_mm=length + head_height,
        parameters={"d": diameter, "L": length, "pitch": pitch,
                    "s": across_flats, "k": head_height},
        features=[FeatureSpec(type="chamfer", size_mm=max(0.5, diameter * 0.08), source=source)],
        assumptions=[] if length_mm else ["未提供螺栓长度，采用 L=4d 的概念长度。"],
        standards=["GB/T 5782-2016"],
        source_text=source_text,
    )


def design_flange(outer_diameter, bore_diameter, thickness, source_text,
                  hole_count=8, pcd=None, hole_diameter=11.0, material="Q235B"):
    """Create a typed flange spec using the existing GB/T 9112 design policy."""
    outer = float(outer_diameter)
    bore = float(bore_diameter)
    thick = float(thickness)
    holes = int(hole_count)
    hole_d = float(hole_diameter)
    pitch_circle = float(pcd) if pcd is not None else round((outer + bore) / 2.0, 1)
    pitch_circle = max(bore + hole_d, min(pitch_circle, outer - hole_d - 2.0))
    if not (0 < bore < pitch_circle < outer):
        raise ValueError("法兰尺寸关系必须满足 0 < 内径 < 分度圆 < 外径")
    return PartSpec(
        part_type="flange", name="Flange_D%g" % outer, material=material,
        total_length_mm=thick,
        parameters={"D": outer, "d": bore, "t": thick, "n": holes,
                    "pcd": pitch_circle, "hole_d": hole_d, "chamfer": min(2.0, thick / 4.0)},
        assumptions=[] if pcd is not None else ["未提供分度圆，采用 (D+d)/2 并按边距约束修正。"],
        standards=["GB/T 9112", "GB/T 1800.2"], source_text=source_text,
    )


def design_hole_plate(length, width, thickness, source_text,
                      hole_count=4, hole_diameter=12.0, material="Q235B"):
    """Create a typed rectangular plate spec with symmetric hole layout."""
    length, width, thickness = float(length), float(width), float(thickness)
    hole_count, hole_diameter = int(hole_count), float(hole_diameter)
    if hole_count not in (1, 2, 4):
        raise ValueError("首版带孔板支持 1、2 或 4 个孔")
    margin_x = max(hole_diameter * 1.5, length * 0.15)
    margin_y = max(hole_diameter * 1.5, width * 0.15)
    if margin_x * 2 >= length or margin_y * 2 >= width:
        raise ValueError("板尺寸不足以满足孔边距")
    return PartSpec(
        part_type="plate", name="HolePlate_%gx%g" % (length, width), material=material,
        total_length_mm=thickness,
        parameters={"length": length, "width": width, "thickness": thickness,
                    "hole_count": hole_count, "hole_d": hole_diameter,
                    "margin_x": margin_x, "margin_y": margin_y},
        assumptions=["孔位按板中心对称布置，边距由孔径与板尺寸共同确定。"],
        standards=["GB/T 1800.2", "GB/T 1184"], source_text=source_text,
    )
