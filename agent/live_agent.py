"""Natural-language planning and execution for the running FreeCAD GUI."""

from __future__ import annotations

import json
import base64
import math
import re
import uuid
from pathlib import Path

from agent.live_schema import CadOperation, CadPlan, LiveAgentResult, PartSpec
from backend.live_freecad_executor import live_executor
from config import settings
from inspection import rules as inspection_rules
from knowledge_base.live_design import (
    design_bolt, design_flange, design_hole_plate, design_stepped_shaft,
)


def _dimension_from_text(text: str, keyword: str, default=None):
    patterns = [
        r"%s[^\d]*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?" % keyword,
        r"(?:直径|轴径|[ØΦ⌀])\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return default


def _is_model_edit(query: str) -> bool:
    return any(token in query for token in ("改成", "修改", "增加键槽", "加键槽", "删除圆角", "倒角改"))


def _is_drawing_request(query: str) -> bool:
    normalized = "".join(str(query).split())
    explicit = any(token in normalized for token in (
        "生成机械零件图", "生成零件图", "出零件图", "出工程图", "绘制零件图", "绘制工程图",
    ))
    compositional = (
        any(noun in normalized for noun in ("零件图", "工程图"))
        and any(verb in normalized for verb in ("生成", "绘制", "创建", "出"))
    )
    return explicit or compositional


def _find_object(tree, predicate, description):
    found = next((item for item in tree.get("objects", []) if predicate(item)), None)
    if found is None:
        raise RuntimeError("活动模型中未找到%s" % description)
    return found


def _keyway_size(diameter):
    """GB/T 1095 subset shared with the existing engineering knowledge base."""
    if diameter < 30:
        return 8.0, 4.0
    if diameter < 38:
        return 10.0, 5.0
    if diameter < 44:
        return 12.0, 5.0
    return 14.0, 5.5


async def _observe_model(tag: str, output_dir: Path, expectations=None):
    """Observe structure and pixels, then evaluate deterministic CAD invariants."""
    tree = await live_executor.get_objects(all_properties=True)
    await live_executor.prepare_view("model")
    view = await live_executor.get_view("Isometric", width=1024, height=768)
    image_path = output_dir / (tag + ".png")
    image_path.write_bytes(base64.b64decode(view["image_base64"]))
    objects = tree.get("objects", [])
    failures = []
    for expected in expectations or []:
        matches = [item for item in objects
                   if item.get("name") == expected or item.get("type_id") == expected]
        if not matches:
            failures.append("missing: %s" % expected)
    invalid = [item.get("name") for item in objects
               if any(str(state).lower() in {"invalid", "error", "touched"}
                      for state in item.get("state", []))]
    if invalid:
        failures.append("invalid objects: %s" % ", ".join(invalid))
    return {"tree": tree, "view_path": str(image_path),
            "evaluation": {"passed": not failures, "failures": failures,
                           "object_count": len(objects)}}


async def modify_active_model(query: str) -> dict:
    """Build and execute an incremental CadPlan against the active model."""
    before = await live_executor.get_objects(all_properties=True)
    body = _find_object(before, lambda o: o.get("type_id") == "PartDesign::Body", "PartDesign Body")
    operations = []
    next_id = 1
    changed = []
    expected = []
    diameter = _dimension_from_text(query, "中间(?:轴段)?(?:直径|轴径)?")

    if diameter is not None and any(token in query for token in ("改", "修改")):
        sketches = [item for item in before.get("objects", [])
                    if item.get("type_id") == "Sketcher::SketchObject"
                    and "keyway" not in item.get("name", "").lower()]
        target = next((item for item in sketches if "segment 2" in item.get("label", "").lower()), None)
        if target is None and len(sketches) >= 2:
            target = sketches[1]
        if target is None:
            raise RuntimeError("找不到中间轴段对应的参数化 Sketch")
        constraint = next((item for item in target.get("constraints", [])
                           if item.get("type") == "Diameter"), None)
        if constraint is None:
            raise RuntimeError("中间轴段 Sketch 没有 Diameter 约束，不能安全修改")
        operations.append(_op(next_id, "set_constraint", "",
                              sketch=target["name"], index=constraint["index"], value=diameter))
        next_id += 1
        changed.append("%s Diameter → Ø%g mm" % (target["name"], diameter))

    if "键槽" in query and any(token in query for token in ("增加", "添加", "加键槽")):
        target_d = diameter
        if target_d is None:
            sketches = [item for item in before.get("objects", [])
                        if item.get("type_id") == "Sketcher::SketchObject"]
            middle = sketches[1] if len(sketches) >= 2 else sketches[0]
            dim = next((item for item in middle.get("constraints", [])
                        if item.get("type") == "Diameter"), None)
            target_d = float(dim["value"]) if dim else 50.0
        width, depth = _keyway_size(target_d)
        radius = target_d / 2.0
        # The design engine's shaft recipe allocates the middle segment to
        # 25%-75% of total length. A 60% keyway leaves ample end margins.
        pads = [item for item in before.get("objects", [])
                if item.get("type_id") == "PartDesign::Pad"]
        lengths = []
        for item in pads[:3]:
            raw = item.get("properties", {}).get("Length", 0)
            match = re.search(r"[-+]?\d+(?:\.\d+)?", str(raw))
            lengths.append(float(match.group()) if match else 0.0)
        first_l = lengths[0] if lengths else 75.0
        middle_l = lengths[1] if len(lengths) > 1 else 150.0
        margin = max(10.0, middle_l * 0.2)
        z0, z1 = first_l + margin, first_l + middle_l - margin
        x0, x1 = radius - depth, radius + 1.0
        points = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]
        operations += [
            _op(next_id, "create_sketch", "keyway_sketch", body=body["name"],
                name="KeywaySketch", label="KeywaySketch — GB/T 1095",
                support_plane="XZ_Plane"),
            _op(next_id + 1, "add_geometry", "", sketch="$keyway_sketch",
                geometry=[{"type": "polygon", "points": points, "closed": True}]),
            _op(next_id + 2, "add_constraint", "", sketch="$keyway_sketch",
                constraints=[{"type": "Block", "geometry": i} for i in range(4)]),
            _op(next_id + 3, "create_pocket", "keyway_pocket", body=body["name"],
                profile="$keyway_sketch", name="KeywayPocket",
                label="KeywayPocket — %gx%gx%g GB/T 1095" % (width, depth, z1-z0),
                length=target_d + 4.0, midplane=True),
        ]
        next_id += 4
        changed.append("增加 GB/T 1095 键槽 %g×%g×%g mm" % (width, depth, z1-z0))
        expected += ["KeywaySketch", "PartDesign::Pocket"]

    chamfer_value = _dimension_from_text(query, "(?:倒角|C)") if "倒角" in query else None
    if chamfer_value is not None and "改" in query:
        chamfer = _find_object(before, lambda o: o.get("type_id") == "PartDesign::Chamfer", "Chamfer")
        operations.append(_op(next_id, "edit_object", "",
                              name=chamfer["name"], properties={"Size": chamfer_value}))
        next_id += 1
        changed.append("%s → C%g" % (chamfer["name"], chamfer_value))

    if "删除圆角" in query:
        fillet = _find_object(before, lambda o: o.get("type_id") == "PartDesign::Fillet", "Fillet")
        operations.append(_op(next_id, "remove_fillet", "", name=fillet["name"]))
        next_id += 1
        changed.append("删除 %s" % fillet["name"])

    if not operations:
        raise ValueError("没有识别出可安全执行的模型修改")
    output_dir = settings.OUTPUT_DIR / "live" / ("edit_" + uuid.uuid4().hex[:12])
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_file = before.get("file_name")
    save_path = existing_file or str(output_dir / (before.get("document") + ".FCStd"))
    operations.append(_op(next_id, "save_document", "saved", path=save_path))
    plan = CadPlan(plan_id=uuid.uuid4().hex[:12], name="AI CAD incremental edit",
                   part_type="shaft_edit", operations=operations,
                   expected_feature_types=expected, output_dir=str(output_dir))
    execution = await live_executor.execute_plan(plan.model_dump())
    observation = await _observe_model("after_edit", output_dir, expected)
    if not observation["evaluation"]["passed"]:
        raise RuntimeError("增量修改后的观察校验失败: %s" % observation["evaluation"]["failures"])
    return {"ok": True, "message": "；".join(changed) + "，已在当前 FreeCAD 模型中完成",
            "cad_plan": plan.model_dump(), "execution": execution,
            "observation": observation, "save_path": save_path}


async def create_current_model_drawing(query: str) -> dict:
    """Create and validate a same-document associative TechDraw drawing."""
    # A dedicated lightweight query avoids serializing every projected edge
    # from an existing TechDraw page before regeneration.
    before = await live_executor.execute_operation("drawing_context")
    source_name = str(before["source"])
    output_dir = settings.OUTPUT_DIR / "live" / ("drawing_" + uuid.uuid4().hex[:12])
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(output_dir / (before.get("document") + "_TechDraw.pdf"))
    save_path = before.get("file_name") or str(output_dir / (before.get("document") + ".FCStd"))
    operations = [
        _op(1, "create_techdraw", "drawing", source=source_name,
            name="DrawingPage", title=str(before.get("label") or before.get("document")),
            material=str((before.get("part_spec") or {}).get("material") or "45钢"),
            part_spec=before.get("part_spec"),
            notes=["Drawing generated from the current Document"]),
        _op(2, "validate_techdraw", "drawing_validation", page="$drawing"),
        _op(3, "export_techdraw_pdf", "drawing_pdf", page="$drawing", path=pdf_path),
        _op(4, "save_document", "saved", path=save_path),
    ]
    plan = CadPlan(plan_id=uuid.uuid4().hex[:12], name="AI CAD current-model TechDraw",
                   part_type="current_model_drawing", operations=operations,
                   expected_feature_types=["TechDraw::DrawPage", "TechDraw::DrawViewPart",
                                           "TechDraw::DrawViewDimension"],
                   output_dir=str(output_dir))
    execution = await live_executor.execute_plan(plan.model_dump())
    drawing_step = execution.get("completed", [])[0]
    drawing_result = drawing_step.get("result", {})
    drawing_page_name = str(drawing_result.get("page", {}).get("name") or "")
    evaluation = drawing_result.get("layout_validation", {})
    if not evaluation.get("passed") or not evaluation.get("inside_border"):
        raise RuntimeError("Drawing layout validated = FAIL: %s" % evaluation)
    await live_executor.prepare_view("drawing", drawing_page_name)
    generated_screenshot = str(output_dir / "techdraw_generated.png")
    generated_capture = await live_executor.capture_gui(generated_screenshot)
    # Generate -> Screenshot -> Inspect -> finite layout correction (inside the
    # layout engine) -> Validate -> Screenshot again.
    validation_check = await live_executor.execute_operation(
        "validate_techdraw", page=drawing_page_name)
    if validation_check.get("drawing_layout_validated") != "PASS":
        raise RuntimeError("Drawing layout validated = FAIL: %s" % validation_check)
    screenshot_path = str(output_dir / "techdraw_validated.png")
    capture = await live_executor.capture_gui(screenshot_path)
    return {"ok": True,
            "message": "已从当前 Document 生成工程图；Mechanical drawing validated = PASS",
            "cad_plan": plan.model_dump(), "execution": execution,
            "evaluation": evaluation, "validation_check": validation_check,
            "pdf_path": pdf_path, "generated_screenshot": generated_screenshot,
            "generated_capture": generated_capture,
            "screenshot_path": screenshot_path, "capture": capture,
            "save_path": save_path}


def parse_live_request(query: str) -> dict:
    text = query.strip()
    if not text:
        raise ValueError("请输入机械零件需求")
    if "盒" in text or "box" in text.lower():
        dims = re.findall(r"(\d+(?:\.\d+)?)", text)
        values = [float(v) for v in dims[:3]]
        while len(values) < 3:
            values.append((50.0, 30.0, 20.0)[len(values)])
        return {"part_type": "box", "length": values[0], "width": values[1], "height": values[2]}
    if "轴" in text:
        patterns = [
            r"(?:长度|长)\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?",
            r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)\s*的?阶梯轴",
            r"创建(?:一个)?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?阶梯轴",
        ]
        length = None
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                length = float(match.group(1))
                break
        if length is None:
            raise ValueError("阶梯轴需要总长度，例如：创建一个300mm阶梯轴")
        torque_match = re.search(r"(?:扭矩|转矩)\s*(\d+(?:\.\d+)?)\s*(?:N\s*[·.]?\s*m|Nm)", text, re.IGNORECASE)
        return {"part_type": "shaft", "total_length_mm": length,
                "torque_nm": float(torque_match.group(1)) if torque_match else None}
    if "法兰" in text:
        def find(label, default=None):
            match = re.search(label + r"\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
            return float(match.group(1)) if match else default
        outer, bore, thick = find("外径"), find("内径"), find("厚(?:度)?")
        if None in (outer, bore, thick):
            raise ValueError("法兰需要外径、内径和厚度")
        holes = re.search(r"(\d+)\s*个?(?:M\d+)?(?:螺栓)?孔", text, re.IGNORECASE)
        metric = re.search(r"(\d+)\s*个?M(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        return {"part_type": "flange", "D": outer, "d": bore, "t": thick,
                "n": int(holes.group(1)) if holes else (int(metric.group(1)) if metric else 8),
                "pcd": find("分度圆(?:直径)?"),
                "hole_d": find("孔径", (float(metric.group(2)) + 1.0) if metric else 11.0)}
    if "板" in text and "孔" in text:
        dims = re.search(r"(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)\s*[xX×*]\s*(\d+(?:\.\d+)?)", text)
        if not dims:
            raise ValueError("带孔板需要 长×宽×厚，例如 120×80×10mm")
        holes = re.search(r"(\d+)\s*个?(?:直径|[ØΦ⌀])?\s*(\d+(?:\.\d+)?)?\s*(?:mm|毫米)?孔", text)
        count = int(holes.group(1)) if holes else 4
        hole_d = float(holes.group(2)) if holes and holes.group(2) else 12.0
        return {"part_type": "plate", "length": float(dims.group(1)),
                "width": float(dims.group(2)), "thickness": float(dims.group(3)),
                "hole_count": count, "hole_d": hole_d}
    bolt = re.search(r"[Mm](\d+(?:\.\d+)?)(?:\s*[xX×*]\s*(\d+(?:\.\d+)?))?", text)
    if "螺栓" in text and bolt:
        diameter = float(bolt.group(1))
        length = float(bolt.group(2)) if bolt.group(2) else diameter * 4.0
        return {"part_type": "bolt", "diameter_mm": diameter, "length_mm": length,
                "length_assumed": bolt.group(2) is None}
    raise ValueError("Live Agent 当前支持：阶梯轴、M规格螺栓、测试盒子")


def build_part_spec(query: str) -> PartSpec:
    intent = parse_live_request(query)
    if intent["part_type"] == "shaft":
        return design_stepped_shaft(intent["total_length_mm"], query, intent.get("torque_nm"))
    if intent["part_type"] == "bolt":
        spec = design_bolt(intent["diameter_mm"], intent["length_mm"], query)
        if intent.get("length_assumed"):
            spec.assumptions.append("未提供螺栓长度，采用 L=4d。")
        return spec
    if intent["part_type"] == "flange":
        return design_flange(intent["D"], intent["d"], intent["t"], query,
                             intent["n"], intent.get("pcd"), intent["hole_d"])
    if intent["part_type"] == "plate":
        return design_hole_plate(intent["length"], intent["width"], intent["thickness"],
                                 query, intent["hole_count"], intent["hole_d"])
    return PartSpec(part_type="box", name="LiveTestBox", source_text=query,
                    parameters={"length": intent["length"], "width": intent["width"],
                                "height": intent["height"]})


def _op(sequence, op, ref="", **params):
    return CadOperation(id="op%02d" % sequence, op=op, ref=ref, params=params)


def compile_cad_plan(spec: PartSpec) -> CadPlan:
    plan_id = uuid.uuid4().hex[:12]
    out_dir = settings.OUTPUT_DIR / "live" / plan_id
    out_dir.mkdir(parents=True, exist_ok=True)
    operations = []
    index = 1

    def add(op, ref="", **params):
        nonlocal index
        operations.append(_op(index, op, ref, **params))
        index += 1

    document_name = re.sub(r"[^A-Za-z0-9_]", "_", spec.name)
    add("create_document", "doc", name=document_name, label=spec.name)
    add("create_body", "body", name="Body", label="Body — " + spec.name)

    expected = ["PartDesign::Body"]
    if spec.part_type == "shaft":
        z = 0.0
        last_feature = ""
        for segment_index, segment in enumerate(spec.segments, 1):
            sketch_ref = "sketch%d" % segment_index
            pad_ref = "pad%d" % segment_index
            sketch_name = "Sketch" if segment_index == 1 else "Sketch%03d" % (segment_index - 1)
            pad_name = "Pad" if segment_index == 1 else "Pad%03d" % (segment_index - 1)
            add("create_sketch", sketch_ref, body="$body", name=sketch_name,
                label="%s — Shaft segment %d" % (sketch_name, segment_index), z_offset=z)
            add("add_geometry", "", sketch="$" + sketch_ref,
                geometry=[{"type": "circle", "center": [0, 0],
                           "radius": segment.diameter_mm / 2.0}])
            add("add_constraint", "", sketch="$" + sketch_ref,
                constraints=[
                    {"type": "Diameter", "geometry": 0, "value": segment.diameter_mm},
                    {"type": "Coincident", "geometry": 0, "point": 3,
                     "other_geometry": -1, "other_point": 1},
                ])
            add("create_pad", pad_ref, body="$body", profile="$" + sketch_ref,
                name=pad_name, label="%s — Ø%g x %g mm" %
                (pad_name, segment.diameter_mm, segment.length_mm),
                length=segment.length_mm)
            expected.extend(["Sketcher::SketchObject", "PartDesign::Pad"])
            last_feature = pad_ref
            z += segment.length_mm
        chamfer = next((f for f in spec.features if f.type == "chamfer"), None)
        if chamfer:
            add("create_chamfer", "chamfer", body="$body", base="$" + last_feature,
                name="Chamfer", size=chamfer.size_mm,
                selector={"kind": "terminal_circular_edges"})
            last_feature = "chamfer"
            expected.append("PartDesign::Chamfer")
        fillet = next((f for f in spec.features if f.type == "fillet"), None)
        if fillet:
            add("create_fillet", "fillet", body="$body", base="$" + last_feature,
                name="Fillet", radius=fillet.size_mm,
                selector={"kind": "shoulder_circular_edges"})
            last_feature = "fillet"
            expected.append("PartDesign::Fillet")
    elif spec.part_type == "bolt":
        d = float(spec.parameters["d"])
        length = float(spec.parameters["L"])
        pitch = float(spec.parameters["pitch"])
        across_flats = float(spec.parameters["s"])
        head_height = float(spec.parameters["k"])
        thread_depth = min(0.6134 * pitch, d * 0.12)
        core_diameter = d - 2.0 * thread_depth
        add("create_sketch", "sketch_shank", body="$body", name="Sketch",
            label="Sketch — M%g shank" % d, z_offset=0)
        add("add_geometry", "", sketch="$sketch_shank",
            geometry=[{"type": "circle", "center": [0, 0], "radius": core_diameter / 2.0}])
        add("add_constraint", "", sketch="$sketch_shank",
            constraints=[
                {"type": "Diameter", "geometry": 0, "value": core_diameter},
                {"type": "Coincident", "geometry": 0, "point": 3,
                 "other_geometry": -1, "other_point": 1},
            ])
        add("create_pad", "pad_shank", body="$body", profile="$sketch_shank",
            name="Pad", label="Pad — M%g thread core" % d, length=length)
        root_radius = core_diameter / 2.0
        thread_points = [
            [round(root_radius - 0.05, 5), 0.0],
            [round(d / 2.0, 5), round(pitch / 2.0, 5)],
            [round(root_radius - 0.05, 5), round(pitch, 5)],
        ]
        radius = across_flats / math.sqrt(3.0)
        points = [[round(radius * math.cos(math.radians(60 * i)), 5),
                   round(radius * math.sin(math.radians(60 * i)), 5)] for i in range(6)]
        add("create_sketch", "sketch_head", body="$body", name="Sketch001",
            label="Sketch001 — Hex head", z_offset=length)
        add("add_geometry", "", sketch="$sketch_head",
            geometry=[{"type": "polygon", "points": points, "closed": True}])
        add("add_constraint", "", sketch="$sketch_head",
            constraints=[{"type": "Block", "geometry": i} for i in range(6)])
        add("create_pad", "pad_head", body="$body", profile="$sketch_head",
            name="Pad001", label="Pad001 — Hex head", length=head_height)
        chamfer = spec.features[0]
        add("create_chamfer", "chamfer", body="$body", base="$pad_head",
            name="Chamfer", size=chamfer.size_mm,
            selector={"kind": "terminal_circular_edges"})
        add("create_sketch", "sketch_thread", body="$body", name="ThreadProfile",
            label="ThreadProfile — M%g × %g" % (d, pitch), support_plane="XZ_Plane")
        add("add_geometry", "", sketch="$sketch_thread",
            geometry=[{"type": "polygon", "points": thread_points, "closed": True}])
        add("add_constraint", "", sketch="$sketch_thread",
            constraints=[{"type": "Block", "geometry": i} for i in range(3)])
        add("create_additive_helix", "thread", body="$body", profile="$sketch_thread",
            name="AdditiveHelix", label="AdditiveHelix — M%g × %g thread" % (d, pitch),
            pitch=pitch, height=length, axis="V_Axis")
        last_feature = "thread"
        expected.extend(["Sketcher::SketchObject", "PartDesign::Pad",
                         "Sketcher::SketchObject", "PartDesign::AdditiveHelix",
                         "Sketcher::SketchObject", "PartDesign::Pad", "PartDesign::Chamfer"])
    elif spec.part_type == "flange":
        p = spec.parameters
        add("create_sketch", "outer_sketch", body="$body", name="Sketch",
            label="Sketch — Flange outer diameter", z_offset=0)
        add("add_geometry", "", sketch="$outer_sketch",
            geometry=[{"type": "circle", "center": [0, 0], "radius": p["D"] / 2.0}])
        add("add_constraint", "", sketch="$outer_sketch",
            constraints=[{"type": "Diameter", "geometry": 0, "value": p["D"]},
                         {"type": "Coincident", "geometry": 0, "point": 3,
                          "other_geometry": -1, "other_point": 1}])
        add("create_pad", "flange_pad", body="$body", profile="$outer_sketch",
            name="Pad", label="Pad — Flange blank", length=p["t"])
        add("create_sketch", "bore_sketch", body="$body", name="Sketch001",
            label="Sketch001 — Central bore", z_offset=p["t"] / 2.0)
        add("add_geometry", "", sketch="$bore_sketch",
            geometry=[{"type": "circle", "center": [0, 0], "radius": p["d"] / 2.0}])
        add("add_constraint", "", sketch="$bore_sketch",
            constraints=[{"type": "Diameter", "geometry": 0, "value": p["d"]},
                         {"type": "Coincident", "geometry": 0, "point": 3,
                          "other_geometry": -1, "other_point": 1}])
        add("create_pocket", "bore_pocket", body="$body", profile="$bore_sketch",
            name="Pocket", label="Pocket — Ø%g through bore" % p["d"],
            length=p["t"] + 2.0, midplane=True)
        holes = []
        for i in range(int(p["n"])):
            angle = 2.0 * math.pi * i / int(p["n"])
            holes.append({"type": "circle",
                          "center": [p["pcd"] / 2.0 * math.cos(angle),
                                     p["pcd"] / 2.0 * math.sin(angle)],
                          "radius": p["hole_d"] / 2.0})
        add("create_sketch", "bolt_sketch", body="$body", name="Sketch002",
            label="Sketch002 — %d bolt holes PCD %g" % (p["n"], p["pcd"]),
            z_offset=p["t"] / 2.0)
        add("add_geometry", "", sketch="$bolt_sketch", geometry=holes)
        add("add_constraint", "", sketch="$bolt_sketch",
            constraints=[{"type": "Block", "geometry": i} for i in range(int(p["n"]))])
        add("create_pocket", "bolt_pocket", body="$body", profile="$bolt_sketch",
            name="Pocket001", label="Pocket001 — Bolt-hole pattern",
            length=p["t"] + 2.0, midplane=True)
        last_feature = "bolt_pocket"
        expected.extend(["Sketcher::SketchObject", "PartDesign::Pad",
                         "Sketcher::SketchObject", "PartDesign::Pocket",
                         "Sketcher::SketchObject", "PartDesign::Pocket"])
    elif spec.part_type == "plate":
        p = spec.parameters
        points = [[0, 0], [p["length"], 0], [p["length"], p["width"]], [0, p["width"]]]
        add("create_sketch", "plate_sketch", body="$body", name="Sketch",
            label="Sketch — Plate outline", z_offset=0)
        add("add_geometry", "", sketch="$plate_sketch",
            geometry=[{"type": "polygon", "points": points, "closed": True}])
        add("add_constraint", "", sketch="$plate_sketch",
            constraints=[{"type": "Block", "geometry": i} for i in range(4)])
        add("create_pad", "plate_pad", body="$body", profile="$plate_sketch",
            name="Pad", label="Pad — %g×%g×%g plate" %
            (p["length"], p["width"], p["thickness"]), length=p["thickness"])
        x0, x1 = p["margin_x"], p["length"] - p["margin_x"]
        y0, y1 = p["margin_y"], p["width"] - p["margin_y"]
        centers = [[p["length"] / 2.0, p["width"] / 2.0]] if p["hole_count"] == 1 else (
            [[x0, p["width"] / 2.0], [x1, p["width"] / 2.0]] if p["hole_count"] == 2
            else [[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
        add("create_sketch", "hole_sketch", body="$body", name="Sketch001",
            label="Sketch001 — Hole pattern", z_offset=p["thickness"] / 2.0)
        add("add_geometry", "", sketch="$hole_sketch",
            geometry=[{"type": "circle", "center": center, "radius": p["hole_d"] / 2.0}
                      for center in centers])
        add("add_constraint", "", sketch="$hole_sketch",
            constraints=[{"type": "Block", "geometry": i} for i in range(len(centers))])
        add("create_pocket", "hole_pocket", body="$body", profile="$hole_sketch",
            name="Pocket", label="Pocket — %d × Ø%g through holes" %
            (len(centers), p["hole_d"]), length=p["thickness"] + 2.0, midplane=True)
        last_feature = "hole_pocket"
        expected.extend(["Sketcher::SketchObject", "PartDesign::Pad",
                         "Sketcher::SketchObject", "PartDesign::Pocket"])
    else:
        raise ValueError("Box uses the direct create_box operation")

    pdf_path = str(out_dir / (document_name + "_drawing.pdf"))
    fcstd_path = str(out_dir / (document_name + ".FCStd"))
    if spec.part_type == "shaft":
        notes = [
            "Associative dimensions: model geometry",
            "Shoulders: R%g; ends C%g" % (
                next((f.size_mm for f in spec.features if f.type == "fillet"), 0),
                next((f.size_mm for f in spec.features if f.type == "chamfer"), 0)),
        ]
    elif spec.part_type == "bolt":
        notes = [
            "Thread designation: M%g" % float(spec.parameters["d"]),
            "Length: %g; pitch: %g" % (float(spec.parameters["L"]),
                                        float(spec.parameters["pitch"])),
            "Across flats: %g; head height: %g" % (float(spec.parameters["s"]),
                                                    float(spec.parameters["k"])),
        ]
    else:
        notes = ["Associative dimensions: model geometry",
                 "Standard review: %s" % ", ".join(spec.standards)]
    add("create_techdraw", "drawing", source="$" + last_feature, name="DrawingPage",
        title=spec.name, material=spec.material, notes=notes,
        part_spec=spec.model_dump(mode="json"))
    add("validate_techdraw", "drawing_validation", page="$drawing")
    add("export_techdraw_pdf", "drawing_pdf", page="$drawing", path=pdf_path)
    add("save_document", "saved", path=fcstd_path)
    expected.extend(["TechDraw::DrawPage", "TechDraw::DrawViewPart"])
    return CadPlan(plan_id=plan_id, name="AI CAD: " + spec.name,
                   part_type=spec.part_type, operations=operations,
                   expected_feature_types=expected, assumptions=spec.assumptions,
                   output_dir=str(out_dir))


def _inspection_params(spec: PartSpec):
    if spec.part_type == "shaft":
        return {"segments": [{"d": s.diameter_mm, "L": s.length_mm} for s in spec.segments],
                "material": spec.material,
                "chamfer": next((f.size_mm for f in spec.features if f.type == "chamfer"), 0),
                "fillet": next((f.size_mm for f in spec.features if f.type == "fillet"), 0)}
    if spec.part_type == "bolt":
        return dict(spec.parameters, material=spec.material)
    if spec.part_type in {"flange", "plate"}:
        return dict(spec.parameters, material=spec.material)
    return spec.parameters


def _write_report(spec, plan, execution, issues):
    path = Path(plan.output_dir) / "design_report.md"
    lines = ["# Live FreeCAD Agent Design Report", "",
             "- Input: %s" % spec.source_text,
             "- Part: %s" % spec.name,
             "- Material: %s" % (spec.material or "—"),
             "- Live Document: %s" % execution.get("document", ""), "",
             "## Assumptions", ""]
    lines.extend("- " + item for item in (spec.assumptions or ["None"]))
    lines += ["", "## Feature Tree", ""]
    for obj in execution.get("tree", {}).get("objects", []):
        lines.append("- `%s` — %s" % (obj.get("name"), obj.get("type_id")))
    lines += ["", "## Inspection", ""]
    if issues:
        for issue in issues:
            lines.append("- [%s] %s: %s" %
                         (issue.get("level"), issue.get("item"), issue.get("suggestion", "")))
    else:
        lines.append("- No rule violations detected.")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


async def run_live_query(query: str) -> dict:
    if _is_model_edit(query):
        return await modify_active_model(query)
    if _is_drawing_request(query):
        return await create_current_model_drawing(query)
    spec = build_part_spec(query)
    if spec.part_type == "box":
        result = await live_executor.execute_operation("create_box", **spec.parameters)
        return {"ok": True, "message": "测试盒子已在当前 FreeCAD 中创建", "execution": result,
                "part_spec": spec.model_dump()}
    plan = compile_cad_plan(spec)
    execution = await live_executor.execute_plan(plan.model_dump())
    params = _inspection_params(spec)
    issues = inspection_rules.check(spec.part_type, params)
    actual_types = [obj.get("type_id") for obj in execution.get("tree", {}).get("objects", [])]
    missing = [type_id for type_id in set(plan.expected_feature_types) if type_id not in actual_types]
    inspection = {"issues": issues, "missing_feature_types": missing,
                  "passed": not missing and not any(i.get("level") == "error" for i in issues)}
    report_path = _write_report(spec, plan, execution, issues)
    if missing:
        raise RuntimeError("Live Feature Tree verification failed, missing: %s" % missing)
    message = "%s 已在 FreeCAD 活动窗口中完成；Document=%s，Feature=%d，报告=%s" % (
        spec.name, execution.get("document", ""),
        len(execution.get("tree", {}).get("objects", [])), report_path)
    result = LiveAgentResult(ok=True, message=message, part_spec=spec,
                             cad_plan=plan, execution=execution,
                             inspection=inspection, report_path=report_path)
    return result.model_dump()
