"""AI CAD Copilot - FastAPI 后端。

REST API 供前端（Vue3/Streamlit）调用，直接驱动 FreeCAD 内核；
LLM Agent 则通过 MCP 协议（stdio）连接 FreeCAD MCP Server。

运行：
    python -m backend.main          # uvicorn 127.0.0.1:8000
"""

import json
import logging
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import settings
from backend.logger import setup_logging, get_logger
from backend.freecad_gateway import (
    FreeCADCommandError,
    FreeCADOfflineError,
    gateway as freecad_gateway,
)
from cad_engine import runner
from inspection import llm_check, rules as rule_checker
from cad_engine.mcp_server.kernel import kernel
from agent import parser, schema

setup_logging()
log = get_logger(__name__)

app = FastAPI(title=settings.get("app", "name", "AI CAD Copilot"),
              version=settings.get("app", "version", "0.2.0"))

# 允许本地前端开发（Vite 默认 5173）与部署同源访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get("app", "cors_origins", ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 全局异常处理 ----------

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """参数校验失败 → 422 统一 JSON。"""
    errs = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg', '')}"
        for e in errs[:5]
    ) or "请求参数无效"
    log.warning("参数校验失败 %s %s -> %s", request.method, request.url.path, detail)
    return JSONResponse(status_code=422, content={"detail": detail, "code": "validation_error"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常 → 统一 JSON（透传状态码）。"""
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": str(exc.detail), "code": "http_error"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """未捕获异常 → 500 统一 JSON（细节仅记日志，不暴露客户端）。"""
    log.exception("未处理异常 %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500,
                        content={"detail": "服务器内部错误，请查看服务端日志", "code": "internal_error"})


# ---------- 报告落盘 ----------

def save_report(kind: str, sid: str, payload: dict) -> str:
    """将审查报告写入 reports/ 目录，返回文件路径。"""
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = settings.get_reports_dir() / f"{stamp}_{sid[:8]}_{kind}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("审查报告已保存 %s", path)
        return str(path)
    except Exception:
        log.exception("报告落盘失败")
        return ""


# ---------- 数据模型 ----------

class ParseRequest(BaseModel):
    text: str = Field(..., description="自然语言零件描述")


class PartRequest(BaseModel):
    part_type: str
    part_name: str = ""
    params: dict = {}


class ChatRequest(BaseModel):
    query: str


class CheckRequest(BaseModel):
    """审查请求：可附带载荷参数（如扭矩 N·m）以启用强度校核规则。"""
    torque_nm: float | None = None


class CreateDocumentRequest(BaseModel):
    name: str = Field("AICADCopilot", min_length=1, max_length=64)


class CreateBoxRequest(BaseModel):
    name: str = Field("AIBox", min_length=1, max_length=64)
    label: str = Field("AI Test Box", min_length=1, max_length=128)
    length: float = Field(50.0, gt=0, le=100000)
    width: float = Field(30.0, gt=0, le=100000)
    height: float = Field(20.0, gt=0, le=100000)


class LiveAgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class LiveViewRequest(BaseModel):
    mode: str = Field("model", pattern="^(model|drawing)$")


class LiveCaptureRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)


class LiveOpenRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)


class LiveObjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class LiveCreateObjectRequest(LiveObjectRequest):
    type_id: str = Field(..., min_length=3, max_length=128)
    label: str = Field("", max_length=128)
    container: str = Field("", max_length=64)
    properties: dict = {}


class LiveEditObjectRequest(BaseModel):
    properties: dict


class LiveDeleteObjectRequest(LiveObjectRequest):
    force: bool = False


class LiveGetViewRequest(BaseModel):
    view_name: str = Field("Isometric")
    width: int | None = Field(default=None, gt=0, le=4096)
    height: int | None = Field(default=None, gt=0, le=4096)
    focus_object: str | None = Field(default=None, max_length=64)


# ---------- 基础接口 ----------

@app.get("/api/health")
def health():
    live = freecad_gateway.status()
    return {
        "ok": True,
        "service": "ai-cad-copilot",
        "pid": os.getpid(),
        # Kept only for the explicitly labelled legacy/offline compatibility
        # flow.  Live Agent commands are dispatched to the connected GUI.
        "freecad_cmd_compat": runner.find_freecad() or "",
        "execution_mode": "live_gui" if live["freecad_online"] else "waiting_for_gui",
        "freecad_version": live.get("freecad_version", ""),
        "freecad_connected": live["freecad_online"],
        "api_key": bool(settings.get_api_key()),
        "output_dir": str(settings.OUTPUT_DIR),
    }


# ---------- Live FreeCAD Bridge ----------

@app.websocket("/ws/freecad")
async def freecad_bridge(websocket: WebSocket):
    """WebSocket endpoint used by the Add-on running inside FreeCAD GUI."""
    await freecad_gateway.serve(websocket)


@app.get("/api/freecad/status")
def freecad_status():
    """Return the current live FreeCAD GUI connection state."""
    return freecad_gateway.status()


@app.get("/api/freecad/events")
def freecad_events():
    return {"events": freecad_gateway.events()}


@app.post("/api/freecad/create-document")
async def live_create_document(req: CreateDocumentRequest):
    try:
        result = await freecad_gateway.execute("create_document", req.model_dump())
        return {"ok": True, **result}
    except FreeCADOfflineError as exc:
        raise HTTPException(503, str(exc))
    except FreeCADCommandError as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/freecad/create-box")
async def live_create_box(req: CreateBoxRequest | None = None):
    """Create a native Part::Box in the active, running FreeCAD document."""
    payload = (req or CreateBoxRequest()).model_dump()
    try:
        result = await freecad_gateway.execute("create_box", payload)
        return {"ok": True, **result}
    except FreeCADOfflineError as exc:
        raise HTTPException(503, str(exc))
    except FreeCADCommandError as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/freecad/document")
async def live_document_info():
    from backend.live_freecad_executor import live_executor

    try:
        return {"ok": True, **await live_executor.inspect_document()}
    except FreeCADOfflineError as exc:
        raise HTTPException(503, str(exc))
    except FreeCADCommandError as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/freecad/objects")
async def live_get_objects(all_properties: bool = False):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.get_objects(all_properties)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.get("/api/freecad/objects/{name}")
async def live_inspect_object(name: str):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.inspect_object(name)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/objects")
async def live_create_object(req: LiveCreateObjectRequest):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.create_object(**req.model_dump())}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.patch("/api/freecad/objects/{name}")
async def live_edit_object(name: str, req: LiveEditObjectRequest):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.edit_object(name, req.properties)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.delete("/api/freecad/objects/{name}")
async def live_delete_object(name: str, force: bool = False):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.delete_object(name, force)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/get-view")
async def live_get_view(req: LiveGetViewRequest):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.get_view(**req.model_dump())}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/agent")
async def live_agent_query(req: LiveAgentRequest):
    """Natural language → Design Engine → CadPlan → running FreeCAD GUI."""
    from agent.live_agent import run_live_query

    try:
        return await run_live_query(req.query.strip())
    except FreeCADOfflineError as exc:
        raise HTTPException(503, str(exc))
    except (FreeCADCommandError, ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/freecad/view")
async def live_prepare_view(req: LiveViewRequest):
    from backend.live_freecad_executor import live_executor

    try:
        return {"ok": True, **await live_executor.prepare_view(req.mode)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/capture")
async def live_capture(req: LiveCaptureRequest):
    from backend.live_freecad_executor import live_executor

    try:
        return {"ok": True, **await live_executor.capture_gui(req.path)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/undo")
async def live_undo():
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.undo()}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/redo")
async def live_redo():
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.redo()}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/freecad/reopen")
async def live_reopen(req: LiveOpenRequest):
    from backend.live_freecad_executor import live_executor
    try:
        return {"ok": True, **await live_executor.reopen_document(req.path)}
    except (FreeCADOfflineError, FreeCADCommandError) as exc:
        raise HTTPException(503 if isinstance(exc, FreeCADOfflineError) else 400, str(exc))


@app.post("/api/parse")
def parse(req: ParseRequest):
    """自然语言 → 结构化零件参数（DeepSeek 抽取，无 Key 时规则回退）。"""
    if not req.text.strip():
        raise HTTPException(400, "请输入零件描述")
    try:
        spec = parser.parse(
            req.text.strip(),
            settings.get_api_key(),
            settings.get_api_base(),
            settings.get_model(),
        )
        return {"ok": True, "spec": spec}
    except Exception as e:
        raise HTTPException(422, f"参数解析失败：{e}")


@app.get("/api/part-types")
def part_types():
    """可用零件类型、字段与示例（前端渲染参数表单用）。"""
    from cad_engine.parts import load_part_meta
    return {"parts": load_part_meta()}


# ---------- 会话接口 ----------

@app.post("/api/sessions")
def create_session():
    s = kernel.create_session()
    return s.state()


@app.get("/api/sessions")
def list_sessions():
    return {"sessions": kernel.list_sessions()}


@app.get("/api/sessions/{sid}")
def session_info(sid: str):
    try:
        s = kernel.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    info = s.state()
    result_path = os.path.join(s.dir, "result.json")
    if os.path.isfile(result_path):
        with open(result_path, encoding="utf-8") as f:
            info["result"] = json.load(f)
    return info


@app.delete("/api/sessions/{sid}")
def close_session(sid: str):
    if not kernel.close_session(sid):
        raise HTTPException(404, "会话不存在或已过期")
    return {"closed": True}


@app.post("/api/sessions/{sid}/parts")
def create_part(sid: str, req: PartRequest):
    """在会话中创建零件（FreeCAD 无头建模，耗时约 10~60s）。"""
    try:
        return kernel.create_part(sid, req.model_dump())
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.post("/api/sessions/{sid}/drawing")
def make_drawing(sid: str):
    try:
        return kernel.make_drawing(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.post("/api/sessions/{sid}/validate")
def validate(sid: str, req: CheckRequest | None = None):
    """规则审查：决策系统（加工/强度/装配/标准）+ 输出完整性。

    body 可选：{"torque_nm": 500} 启用扭矩强度校核。
    """
    try:
        s = kernel.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    spec_path = os.path.join(s.dir, "params.json")
    if not os.path.isfile(spec_path):
        raise HTTPException(400, "会话中还没有零件，请先创建")
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    torque = (req or CheckRequest()).torque_nm
    issues = rule_checker.check(spec.get("part_type"), spec.get("params", {}),
                                torque_nm=torque)
    result_path = os.path.join(s.dir, "result.json")
    if os.path.isfile(result_path):
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        issues += rule_checker.check_outputs(result)
    payload = {"session_id": sid, "part_type": spec.get("part_type"),
               "part_name": spec.get("part_name"), "kind": "rule",
               "issues": issues,
               # 通过标准：无 error/warning（info 为建议性提示，不影响通过）
               "passed": not any(i.get("level") in ("error", "warning") for i in issues)}
    payload["report_path"] = save_report("rule", sid, payload)
    return payload


@app.post("/api/sessions/{sid}/review")
def review(sid: str, req: CheckRequest | None = None):
    """LLM 深度审查（DeepSeek），需配置 API Key。

    body 可选：{"torque_nm": 500} 让决策系统与 LLM 审查做扭矩强度校核。
    """
    if not settings.get_api_key():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY，无法进行 LLM 审查")
    try:
        s = kernel.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    spec_path = os.path.join(s.dir, "params.json")
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    torque = (req or CheckRequest()).torque_nm
    rule_issues = rule_checker.check(spec.get("part_type"), spec.get("params", {}),
                                     torque_nm=torque)
    res = llm_check.llm_review(
        spec.get("part_type"),
        spec.get("params", {}),
        rule_issues,
        settings.get_api_key(),
        settings.get_api_base(),
        settings.get_model(),
    )
    payload = {"session_id": sid, "part_type": spec.get("part_type"),
               "part_name": spec.get("part_name"), "kind": "llm",
               "rule_issues": rule_issues, **res}
    payload["report_path"] = save_report("llm", sid, payload)
    return payload


@app.post("/api/sessions/{sid}/drawing-review")
def drawing_review(sid: str):
    """工程图审查：解析会话的 SVG/DXF/PDF 工程图，校验标注与参数一致性。"""
    try:
        s = kernel.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    spec_path = os.path.join(s.dir, "params.json")
    if not os.path.isfile(spec_path):
        raise HTTPException(400, "会话中还没有零件，请先创建")
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    from inspection import reviewer

    results = {}
    for name in os.listdir(s.dir):
        if name.lower().endswith((".svg", ".dxf", ".pdf")):
            results[name] = reviewer.review_drawing(os.path.join(s.dir, name), spec)
    if not results:
        raise HTTPException(400, "会话中没有可审查的工程图文件（SVG/DXF/PDF）")
    passed = all(r["passed"] for r in results.values())
    payload = {"session_id": sid, "part_type": spec.get("part_type"),
               "part_name": spec.get("part_name"), "kind": "drawing",
               "files": results, "passed": passed}
    payload["report_path"] = save_report("drawing", sid, payload)
    return payload


@app.post("/api/sessions/{sid}/step-review")
def step_review(sid: str):
    """STEP 模型审查（OpenCascade 特征提取 + 可制造性/加工风险/设计缺陷评估）。"""
    try:
        s = kernel.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    step_path = ""
    for fn in os.listdir(s.dir):
        if fn.lower().endswith(".step"):
            step_path = os.path.join(s.dir, fn)
            break
    if not step_path:
        raise HTTPException(400, "会话中没有 STEP 文件，请先创建零件")
    from inspection import step_reviewer

    try:
        report = step_reviewer.review_step(step_path, s.dir)
        return {"session_id": sid, **report}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.get("/api/sessions/{sid}/files/{filename:path}")
def download(sid: str, filename: str):
    """下载会话中的生成文件（FCStd/STEP/STL/SVG/PDF/DXF）。"""
    try:
        s = kernel.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff\.\-]+", filename):
        raise HTTPException(400, "非法文件名")
    path = Path(s.dir) / filename
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=filename)


# ---------- Agent 对话 ----------

class DesignAnalyzeRequest(BaseModel):
    """设计参数合理性分析请求。"""
    torque_nm: float
    diameter: float | None = None
    length: float = 0
    material: str = "45钢"
    part_type: str | None = None
    params: dict | None = None


@app.post("/api/design/analyze")
def design_analyze(req: DesignAnalyzeRequest):
    """Engineering Decision Engine：参数合理性分析 + 设计报告。"""
    from knowledge_base import decision_engine

    try:
        if req.part_type and req.params:
            # 完整设计评估（参数 + 工艺 + 装配 + 标准）
            result = decision_engine.evaluate_design(
                req.part_type, req.params, req.torque_nm)
            if req.diameter is None:
                segs = [s for s in (req.params.get("segments") or []) if s.get("d", 0) > 0]
                req.diameter = min((float(s["d"]) for s in segs), default=None)
        else:
            result = {"issues": []}
        # 轴参数合理性分析
        if req.diameter:
            shaft = decision_engine.analyze_shaft(
                req.torque_nm, req.diameter, req.length, req.material)
            result["shaft_analysis"] = shaft
        # 设计报告落盘
        result["report_path"] = _write_design_report(result, req)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(500, f"设计分析失败：{e}")


def _write_design_report(result: dict, req: "DesignAnalyzeRequest") -> str:
    """设计报告（markdown，落盘 reports/）。"""
    from config import settings

    lines = ["# 工程设计决策报告", "",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 载荷：扭矩 {req.torque_nm:g} N·m", ""]

    shaft = result.get("shaft_analysis")
    if shaft:
        d = shaft["design"]
        lines += ["## 1. 参数合理性分析", "",
                  "| 项目 | 数值 |",
                  "|---|---|",
                  f"| 实际扭转应力 τ | {d['tau_actual_mpa']} MPa |",
                  f"| 许用扭转应力 [τ] | {d['tau_allow_mpa']} MPa（{req.material}） |",
                  f"| 安全系数 n | {d['safety_factor']} |",
                  f"| 最小轴径 d_min | {d['d_min_mm']} mm |",
                  f"| 推荐轴径范围 | {d['recommend_d_range_mm'][0]} ~ {d['recommend_d_range_mm'][1]} mm |",
                  f"| 材料建议 | {d['recommend_material']} |",
                  "",
                  f"**当前设计风险：{shaft['risk']}**", "",
                  f"- **原因**：{shaft['analysis']}",
                  f"- **建议**：{shaft['recommendation']}",
                  f"- **依据**：{shaft['standard']}", ""]

    issues = result.get("issues") or []
    if issues:
        lines += ["## 2. 工艺 / 装配 / 标准检查", "",
                  "| 类别 | 级别 | 问题 | 建议 | 依据 |",
                  "|---|---|---|---|---|"]
        for i in issues:
            lines.append(f"| {i.get('category_cn', '—')} | {i.get('level')} | "
                         f"{i.get('item')} | {i.get('suggestion')} | {i.get('standard', '—')} |")
    else:
        lines += ["## 2. 工艺 / 装配 / 标准检查", "", "未发现明显问题。", ""]

    if issues:
        lines += ["## 3. 修改建议", ""]
        for i in issues[:8]:
            lines.append(f"- **{i.get('item')}**：{i.get('suggestion')}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = settings.get_reports_dir() / f"{stamp}_design_decision.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


@app.post("/api/demo/run")
def demo_run():
    """旧版离线 Demo，仅作为兼容验证，不属于 Live Agent 验收路径。"""
    from backend import demo_service
    try:
        result = demo_service.run_demo()
        return {"ok": True, **result}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.get("/api/demo/report")
def demo_report_download():
    """下载最新 Demo 优化报告（examples/demo/demo_report.md）。"""
    p = settings.ROOT_DIR / "examples" / "demo" / "demo_report.md"
    if p.is_file():
        return FileResponse(p, filename="demo_report.md")
    raise HTTPException(404, "Demo 报告尚未生成，请先运行 /api/demo/run")


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """自然语言端到端对话（Agent → MCP → FreeCAD 建模），需配置 API Key。"""
    if not settings.get_api_key():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY，请先在 .env 中设置")
    from agent import agent
    try:
        answer = await agent.run_query(req.query)
        return {"ok": True, "answer": answer}
    except Exception as e:
        raise HTTPException(500, f"Agent 执行失败：{e}")


# ---------- 静态资源（前端构建产物，可选） ----------

_frontend = settings.ROOT_DIR / "frontend" / "dist"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app",
                host=settings.get("app", "host", "127.0.0.1"),
                port=int(settings.get("app", "port", 8000)),
                reload=False)
