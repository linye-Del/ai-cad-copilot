"""Live Agent domain/planning tests; no FreeCAD process is required."""

from agent.live_agent import build_part_spec, compile_cad_plan, parse_live_request
from freecad_addon.AICADCopilot.bridge.security import validate_backend_url


def test_parse_natural_language_shaft_length():
    intent = parse_live_request("创建一个300mm阶梯轴")
    assert intent == {"part_type": "shaft", "total_length_mm": 300.0, "torque_nm": None}


def test_design_engine_generates_dynamic_shaft_spec():
    spec = build_part_spec("创建一个420mm阶梯轴")
    assert spec.part_type == "shaft"
    assert sum(segment.length_mm for segment in spec.segments) == 420.0
    assert len({segment.diameter_mm for segment in spec.segments}) == 2
    assert spec.assumptions


def test_shaft_plan_uses_native_partdesign_features():
    spec = build_part_spec("创建一个300mm阶梯轴")
    plan = compile_cad_plan(spec)
    operations = [operation.op for operation in plan.operations]
    assert operations.count("create_sketch") == 3
    assert operations.count("create_pad") == 3
    assert "create_chamfer" in operations
    assert "create_fillet" in operations
    assert operations[-4:] == ["create_techdraw", "validate_techdraw",
                               "export_techdraw_pdf", "save_document"]
    assert "PartDesign::Pad" in plan.expected_feature_types


def test_m10_bolt_plan_is_not_prebuilt_file():
    spec = build_part_spec("创建一个M10螺栓")
    assert spec.parameters["d"] == 10
    assert spec.parameters["L"] == 40
    plan = compile_cad_plan(spec)
    operations = [operation.op for operation in plan.operations]
    assert operations.count("create_sketch") == 3
    assert operations.count("create_pad") == 2
    assert "create_additive_helix" in operations
    assert "save_document" in operations


def test_flange_request_uses_native_partdesign_holes():
    spec = build_part_spec("法兰 外径160 内径50 厚度18，8个M10螺栓孔，分度圆直径130")
    assert spec.part_type == "flange"
    assert spec.parameters["D"] == 160
    assert spec.parameters["d"] == 50
    assert spec.parameters["n"] == 8
    assert spec.parameters["hole_d"] == 11
    plan = compile_cad_plan(spec)
    operations = [operation.op for operation in plan.operations]
    assert operations.count("create_sketch") == 3
    assert operations.count("create_pocket") == 2
    assert "PartDesign::Pocket" in plan.expected_feature_types


def test_hole_plate_request_uses_native_partdesign_pocket():
    spec = build_part_spec("创建120×80×10mm带4个直径12mm孔的板")
    assert spec.part_type == "plate"
    assert spec.parameters["length"] == 120
    assert spec.parameters["width"] == 80
    assert spec.parameters["thickness"] == 10
    assert spec.parameters["hole_count"] == 4
    assert spec.parameters["hole_d"] == 12
    plan = compile_cad_plan(spec)
    operations = [operation.op for operation in plan.operations]
    assert operations.count("create_sketch") == 2
    assert operations.count("create_pocket") == 1
    assert "PartDesign::Pocket" in plan.expected_feature_types


def test_bridge_rejects_non_local_gateway():
    assert validate_backend_url("ws://127.0.0.1:8000/ws/freecad")
    try:
        validate_backend_url("ws://example.com:8000/ws/freecad")
    except ValueError as exc:
        assert "localhost" in str(exc)
    else:
        raise AssertionError("remote gateway must be rejected")
