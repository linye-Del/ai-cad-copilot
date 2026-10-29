"""FreeCAD MCP Server（FastMCP 实现）。

暴露工具：
- create_session / list_sessions / close_session
- create_part / get_part_info / make_drawing / validate_part
- list_part_types

运行：
    python -m cad_engine.mcp_server.server            # stdio 模式
    python backend/mcp_server/standalone.py        # streamable http 模式
"""

import json
import os
from pathlib import Path

from fastmcp import FastMCP

from config import settings
from cad_engine.mcp_server.kernel import kernel
from cad_engine.parts import PARTS, load_part_meta

mcp = FastMCP("freecad-mcp", instructions=(
    "你是机械设计 CAD 助手。首选 get_live_freecad_status 和 execute_live_freecad，"
    "通过正在运行的 FreeCAD GUI 创建原生参数化 Feature Tree。"
    "create_session/create_part/make_drawing 仅为旧版离线兼容工具。"
))


def _norm_spec(part_type: str, part_name: str, params: dict) -> dict:
    if not part_type or part_type not in PARTS:
        raise ValueError(f"不支持的零件类型: {part_type}，可用: {sorted(PARTS)}")
    return {"part_type": part_type, "part_name": part_name or part_type, "params": params or {}}


@mcp.tool()
def create_session() -> dict:
    """创建一个新的建模会话，返回 session_id（后续所有操作都基于它）。"""
    return kernel.create_session().state()


@mcp.tool()
def list_sessions() -> list[dict]:
    """列出所有活跃会话及其文件状态。"""
    return kernel.list_sessions()


@mcp.tool()
def close_session(session_id: str) -> dict:
    """关闭并删除指定会话，释放资源。"""
    return {"closed": kernel.close_session(session_id)}


@mcp.tool()
def list_part_types() -> list[dict]:
    """列出所有支持的零件类型、参数字段和示例。"""
    out = []
    for key, meta in load_part_meta().items():
        out.append({"key": key, "name": meta["name"], "name_en": meta["name_en"],
                    "standard": meta.get("standard", ""), "fields": meta["fields"],
                    "examples": meta.get("examples", [])})
    return out


@mcp.tool()
async def get_live_freecad_status() -> dict:
    """检查 FreeCAD GUI Add-on 是否在线，以及当前 Document/对象/版本。"""
    from backend.freecad_gateway import gateway

    return gateway.status()


@mcp.tool()
async def execute_live_freecad(query: str) -> dict:
    """把普通语言需求交给 Design Engine，并在正在运行的 FreeCAD GUI 中执行 CadPlan。

    当前支持动态尺寸的阶梯轴与 M 规格六角头螺栓。此工具不会调用 FreeCADCmd，
    也不会让 LLM 生成或执行任意 Python。
    """
    from agent.live_agent import run_live_query

    return await run_live_query(query)


@mcp.tool()
def create_part(session_id: str, part_type: str, part_name: str, params: dict) -> dict:
    """在会话中创建 3D 零件。

    Args:
        session_id: 会话 ID（create_session 返回）
        part_type: 零件类型 bolt/shaft/flange/gear
        part_name: 零件名称（如 "M10x40六角头螺栓"）
        params: 参数字典，见 list_part_types 中各类型的 fields
    """
    spec = _norm_spec(part_type, part_name, params)
    return kernel.create_part(session_id, spec)


@mcp.tool()
def get_part_info(session_id: str) -> dict:
    """获取会话中零件的完整信息：参数、派生尺寸、材料、生成的文件列表。"""
    from cad_engine.mcp_server.kernel import Session

    s = kernel.get_session(session_id)
    info = {"session_id": session_id, "files": [], "params": None, "errors": []}
    result_path = os.path.join(s.dir, "result.json")
    if os.path.isfile(result_path):
        with open(result_path, encoding="utf-8") as f:
            r = json.load(f)
        info["files"] = r.get("files", {})
        info["ok"] = r.get("ok", False)
        info["errors"] = r.get("errors", [])
    params_path = os.path.join(s.dir, "params.json")
    if os.path.isfile(params_path):
        with open(params_path, encoding="utf-8") as f:
            info["params"] = json.load(f)
    return info


@mcp.tool()
def make_drawing(session_id: str) -> dict:
    """为会话中的零件生成工程图（TechDraw 三视图 + 尺寸标注 + 标题栏）。"""
    return kernel.make_drawing(session_id)


@mcp.tool()
def validate_part(session_id: str) -> dict:
    """按机械设计规则（GB/T 标准、公差、加工可行性）审查零件，返回问题列表。"""
    from inspection.rules import check

    s = kernel.get_session(session_id)
    spec_path = os.path.join(s.dir, "params.json")
    spec = {}
    if os.path.isfile(spec_path):
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
    issues = []
    if spec:
        issues = check(spec.get("part_type"), spec.get("params", {}))
    return {"session_id": session_id, "issues": issues, "passed": len(issues) == 0}


if __name__ == "__main__":
    mcp.run()
