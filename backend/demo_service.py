"""Demo 展示模式：3 分钟完整机械设计流程（前端一键运行）。

7 步流程：
  用户需求 → AI 需求理解 → 机械参数推荐 → FreeCAD CAD 生成
  → 工程图生成 → CAD 智能审查 → 优化建议输出

交付物（examples/demo/）：
  demo_input.json   输入定义
  demo_output.json  本次运行完整存档（可复现）
  demo_report.md    设计分析 + 审查报告
  model.FCStd       三维模型
  drawing.svg       工程图
"""

import json
import logging
import os
import shutil
import time

from config import settings

log = logging.getLogger("backend.demo")

DEMO_DIR = settings.ROOT_DIR / "examples" / "demo"
INPUT_PATH = DEMO_DIR / "demo_input.json"

STEP_TITLES = {
    "input": "用户需求",
    "analysis": "AI 需求理解",
    "recommend": "机械参数推荐",
    "model": "FreeCAD CAD 生成",
    "drawing": "工程图生成",
    "review": "CAD 智能审查",
    "report": "优化建议输出",
}


def _load_input() -> dict:
    with open(INPUT_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_demo() -> dict:
    """执行完整 Demo 流程（复用案例脚本的参数推荐逻辑）。"""
    from scripts.case_motor_shaft import recommend_params  # namespace package

    from cad_engine.mcp_server.kernel import kernel
    from inspection import llm_check, rules as rule_checker
    from inspection.step_review import review_step
    from agent import parser

    conf = _load_input()
    text = conf["input"]["text"]
    t_start = time.time()
    result = {"case": conf["case"], "steps": {}, "created": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 1. 用户需求
    result["steps"]["input"] = {"text": text}

    # 2. AI 需求理解（DeepSeek 参数抽取）
    spec = parser.parse(text, settings.get_api_key(), settings.get_api_base(),
                        settings.get_model())
    result["steps"]["analysis"] = spec

    # 3. 机械参数推荐（扭转强度校核 + 标准件选型）
    legacy_conf = {
        "user_input": {"requirements": conf["input"]["requirements"],
                       "text": conf["input"]["text"]},
        "design_constraints": conf["design_constraints"],
    }
    reco = recommend_params(legacy_conf)
    result["steps"]["recommend"] = reco

    # 4. FreeCAD CAD 生成
    sid = kernel.create_session().id
    model = kernel.create_part(sid, {"part_type": reco["part_type"],
                                     "part_name": reco["part_name"],
                                     "params": reco["params"]})
    result["steps"]["model"] = {"session_id": sid, "ok": model.get("ok"),
                                "files": model.get("files"),
                                "retries": model.get("retries")}

    # 5. 工程图生成
    drawing = kernel.make_drawing(sid)
    svg = drawing.get("drawing", {}).get("svg", "")
    result["steps"]["drawing"] = {"svg": svg, "ok": bool(svg)}

    # 6. CAD 智能审查（规则 + STEP + LLM）
    torque = conf["input"]["requirements"]["torque_nm"]
    rule_issues = rule_checker.check(reco["part_type"], reco["params"], torque_nm=torque)
    sess_dir = os.path.join(settings.OUTPUT_DIR, "sessions", sid)
    step_report = review_step(model["files"]["step"], sess_dir)
    step_issues = step_report["problems"]
    llm_issues = llm_check.llm_review(
        reco["part_type"], reco["params"], rule_issues,
        settings.get_api_key(), settings.get_api_base(), settings.get_model()
    ).get("issues", [])
    review = {"rule": rule_issues, "step": step_issues, "llm": llm_issues,
              "rule_passed": not any(i.get("level") in ("error", "warning") for i in rule_issues),
              "step_passed": len(step_issues) == 0}
    result["steps"]["review"] = review

    # 7. 优化建议输出（报告落盘 examples/demo/）
    report_path = _write_report(result, reco, model, svg, llm_issues)
    result["steps"]["report"] = {"report_path": report_path,
                                 "demo_output_json": _write_output(result)}

    result["duration_s"] = round(time.time() - t_start, 1)
    log.info("Demo 流程完成: %.1fs", result["duration_s"])
    return result


def _write_output(result: dict) -> str:
    path = DEMO_DIR / "demo_output.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _write_report(result: dict, reco: dict, model: dict, svg: str, llm_issues: list) -> str:
    """设计分析 + 审查报告（可复现覆盖）。"""
    steps = result["steps"]
    calc = reco["strength"]
    segs = reco["params"]["segments"]
    seg_txt = " / ".join(f"{s['d']}×{s['L']}" for s in segs)
    kw = reco["params"]["keyway"]
    review = steps["review"]
    all_issues = review["rule"] + review["step"] + llm_issues

    lines = [f"# {result['case']['name']} —— 设计分析与审查报告", "",
             f"- 生成时间：{result['created']}",
             f"- 输入需求：{steps['input']['text']}", ""]

    lines += ["## 1. 设计分析", "",
              "| 项目 | 数值 | 依据 |",
              "|---|---|---|",
              f"| 传递扭矩 T | {calc['torque_nm']} N·m | 用户输入 |",
              f"| 许用扭转应力 [τ] | {calc['tau_allow_mpa']} MPa | 45钢调质 (GB/T 699) |",
              f"| 最小轴径 d_min | {calc['d_min_mm']} mm | τ=16T/(πd³) 校核 |",
              f"| 推荐轴端直径 | {calc['d_recommend_mm']} mm | 键槽削弱系数 1.08 |",
              f"| 轴段 (d×L) | {seg_txt} | 总长 {sum(s['L'] for s in segs)}mm |",
              f"| 材料 | {reco['params']['material']} | 调质 217~255HBW |",
              f"| 轴承 | {reco['bearing']['type']} | GB/T 276 |",
              f"| 联轴器 | {reco['coupling']['type']} | 弹性柱销联轴器 |",
              f"| 键槽 | GB/T 1095 键 {kw['w']}×{round(kw['t'] + 3.5)}×{kw['lk']} (d{segs[0]['d']} 段) | 轴槽深 t={kw['t']}mm |",
              ""]

    lines += ["## 2. CAD 智能审查", "",
              f"- 决策系统规则：{'通过' if review['rule_passed'] else str(len(review['rule'])) + ' 项问题'}"
              f"｜STEP 模型审查：{'通过' if review['step_passed'] else str(len(review['step'])) + ' 项问题'}"
              f"｜LLM 深度审查：{len(llm_issues)} 项补充问题", ""]
    if all_issues:
        lines += ["| 级别 | 来源 | 问题 | 建议 |", "|---|---|---|---|"]
        src_map = {}
        for i in review["rule"]: src_map[id(i)] = "规则"
        for i in review["step"]: src_map[id(i)] = "STEP"
        for i in llm_issues: src_map[id(i)] = "LLM"
        for i in all_issues[:12]:
            lines.append(f"| {i.get('level') or i.get('risk')} | {src_map.get(id(i), '—')} | "
                         f"{i.get('item') or i.get('feature')} | "
                         f"{i.get('suggestion') or i.get('solution', '')} |")

    lines += ["", "## 3. 优化建议", ""]
    for i in all_issues[:8]:
        lines.append(f"- **{i.get('item') or i.get('feature')}**："
                     f"{i.get('suggestion') or i.get('solution', '')}"
                     f"{'（' + str(i.get('standard', '')).strip() + '）' if i.get('standard') else ''}")

    lines += ["", "## 4. 交付物", "",
              "- `demo_input.json`：输入需求定义",
              "- `demo_output.json`：完整流程存档（可复现）",
              "- `model.FCStd`：三维模型",
              "- `drawing.svg`：工程图", ""]
    # 复制交付物
    os.makedirs(DEMO_DIR, exist_ok=True)
    for key in ("fcstd",):
        p = (model.get("files") or {}).get(key, "")
        if p and os.path.isfile(p):
            shutil.copy(p, DEMO_DIR / "model.FCStd")
    if svg and os.path.isfile(svg):
        shutil.copy(svg, DEMO_DIR / "drawing.svg")
    path = DEMO_DIR / "demo_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)
