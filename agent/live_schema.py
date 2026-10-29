"""Strongly typed domain and execution schemas for the Live CAD Agent."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ParameterSource(BaseModel):
    kind: Literal["user", "design_engine", "standard", "assumption"]
    detail: str


class ShaftSegment(BaseModel):
    diameter_mm: float = Field(gt=0)
    length_mm: float = Field(gt=0)
    source: ParameterSource


class FeatureSpec(BaseModel):
    type: Literal["chamfer", "fillet", "keyway", "thread"]
    size_mm: float | None = Field(default=None, gt=0)
    source: ParameterSource


class PartSpec(BaseModel):
    part_type: Literal["shaft", "bolt", "box", "flange", "plate"]
    name: str
    material: str = ""
    total_length_mm: float | None = Field(default=None, gt=0)
    segments: list[ShaftSegment] = []
    parameters: dict[str, Any] = {}
    features: list[FeatureSpec] = []
    assumptions: list[str] = []
    standards: list[str] = []
    source_text: str = ""

    @model_validator(mode="after")
    def validate_shaft_length(self):
        if self.part_type == "shaft":
            if not self.segments:
                raise ValueError("Shaft PartSpec requires segments")
            total = sum(segment.length_mm for segment in self.segments)
            if self.total_length_mm is not None and abs(total - self.total_length_mm) > 0.01:
                raise ValueError("Shaft segment lengths do not match total length")
        return self


class CadOperation(BaseModel):
    id: str
    op: Literal[
        "create_document", "create_body", "create_sketch", "add_geometry",
        "add_constraint", "set_constraint", "create_pad", "create_revolution", "create_pocket",
        "create_additive_helix", "create_chamfer", "create_fillet", "create_techdraw",
        "validate_techdraw", "drawing_context",
        "create_pattern", "create_hole", "remove_fillet", "create_object", "inspect_object", "edit_object",
        "delete_object", "get_objects", "get_view", "use_active_document",
        "export_techdraw_pdf", "save_document",
    ]
    ref: str = ""
    params: dict[str, Any] = {}


class CadPlan(BaseModel):
    plan_id: str
    name: str
    part_type: str
    operations: list[CadOperation]
    expected_feature_types: list[str] = []
    assumptions: list[str] = []
    output_dir: str


class LiveAgentResult(BaseModel):
    ok: bool
    message: str
    part_spec: PartSpec
    cad_plan: CadPlan
    execution: dict[str, Any]
    inspection: dict[str, Any]
    report_path: str
