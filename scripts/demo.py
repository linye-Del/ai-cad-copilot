"""AI CAD Copilot 3 分钟 Demo：完整流程编排。

流程：
  用户输入需求 → AI 分析 → 显示设计参数 → FreeCAD 生成模型
  → 显示三维模型 → 生成工程图 → AI 审查 → 输出优化报告

案例定义：examples/demo_case.json

用法：
    python scripts/demo.py --http 8000 --case 1
"""

import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


def load_cases() -> dict:
    with open(os.path.join(EXAMPLES_DIR, "demo_case.json"), encoding="utf-8") as f:
        return json.load(f)


def banner(text: str, width: int = 72):
    print("\n" + "=" * width)
    print("  " + text)
    print("=" * width)


def sub(text: str):
    print("\n-- " + text)


class Client:
    def __init__(self, base: str | None):
        self.base = base
        if base:
            import requests
            self.s = requests.Session()

    def req(self, method: str, path: str, body: dict | None = None, timeout: int = 600):
        if self.base:
            r = self.s.request(method, self.base + path, json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app) as c:
            r = c.request(method, path, json=body)
            r.raise_for_status()
            return r.json()


def fmt_params(params: dict) -> str:
    """参数友好展示。"""
    lines = []
    for k, v in params.items():
        if k in ("segments", "keyway", "tolerances"):
            lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def run(client: Client, case: dict, case_idx: int) -> int:
    meta = load_cases()
    steps_meta = {s["id"]: s for s in meta["steps"]}
    timing = case.get("timing_sec", {})
    input_text = case["input"]
    torque = case.get("review_torque_nm")
    t_start = time.time()
    history = {}

    # ---------- 1. 用户输入需求 ----------
    banner(f"[1/8] {steps_meta['input']['title']}")
    print(steps_meta["input"]["description"])
    print("\n用户输入：")
    print(f'  「{input_text}」')
    history["input"] = input_text
    time.sleep(min(timing.get("input", 10), 5))

    # ---------- 2. AI 分析 ----------
    banner(f"[2/8] {steps_meta['analysis']['title']}")
    print("DeepSeek 大模型抽取结构化参数中...")
    t0 = time.time()
    r = client.req("POST", "/api/parse", {"text": input_text}, timeout=180)
    spec = r["spec"]
    print(f"✓ 识别零件：{spec['part_name']}（{spec['part_type']}）  来源：{spec['source']}  [{time.time()-t0:.1f}s]")
    history["analysis"] = spec

    # ---------- 3. 设计参数 ----------
    banner(f"[3/8] {steps_meta['params']['title']}")
    print(steps_meta["params"]["description"])
    print(fmt_params(spec["params"]))
    time.sleep(min(timing.get("params", 15), 6))

    # ---------- 4. FreeCAD 生成模型 ----------
    banner(f"[4/8] {steps_meta['model']['title']}")
    print("FreeCADCmd 无头建模中（首次运行约 30s）...")
    t0 = time.time()
    sid = client.req("POST", "/api/sessions")["id"]
    r = client.req("POST", f"/api/sessions/{sid}/parts",
                   {"part_type": spec["part_type"], "part_name": spec["part_name"],
                    "params": spec["params"]}, timeout=300)
    dt = time.time() - t0
    print(f"✓ 建模完成 [{dt:.0f}s] retries={r.get('retries')}")
    for key, p in (r.get("files") or {}).items():
        print(f"  {key.upper():5s} {os.path.basename(p)}")
    history["model"] = r

    # ---------- 5. 三维模型 ----------
    banner(f"[5/8] {steps_meta['view3d']['title']}")
    stl = (r.get("files") or {}).get("stl", "")
    print(f"STL 网格已生成：{stl}")
    print("→ 前端 three.js WebGL 预览（旋转/缩放）；命令行模式直接打开文件即可查看")
    time.sleep(min(timing.get("view3d", 15), 4))

    # ---------- 6. 工程图 ----------
    banner(f"[6/8] {steps_meta['drawing']['title']}")
    r = client.req("POST", f"/api/sessions/{sid}/drawing", timeout=300)
    svg = r.get("drawing", {}).get("svg", "")
    print(f"✓ SVG 工程图（三视图 + 尺寸标注 + 标题栏）: {os.path.basename(svg)}")
    history["drawing"] = svg

    # ---------- 7. AI 审查 ----------
    banner(f"[7/8] {steps_meta['review']['title']}")
    print("① 决策系统规则 → ② STEP 模型审查 → ③ LLM 深度审查")
    all_issues = []
    # ① 规则
    r = client.req("POST", f"/api/sessions/{sid}/validate",
                   {"torque_nm": torque} if torque else None, timeout=60)
    rule_issues = r.get("issues", [])
    n_ew = sum(1 for i in rule_issues if i.get("level") in ("error", "warning"))
    print(f"① 决策系统规则：{len(rule_issues)} 项（error/warning {n_ew} 项）")
    all_issues += rule_issues
    # ② STEP
    try:
        r = client.req("POST", f"/api/sessions/{sid}/step-review", timeout=300)
        step_problems = r.get("problems", [])
        print(f"② STEP 模型审查：面 {r['features']['faces']}，{len(step_problems)} 项问题")
        all_issues += step_problems
    except Exception as e:
        step_problems = []
        print(f"② STEP 审查跳过：{e}")
    # ③ LLM
    try:
        r = client.req("POST", f"/api/sessions/{sid}/review",
                       {"torque_nm": torque} if torque else None, timeout=240)
        llm_issues = r.get("issues", [])
        print(f"③ LLM 深度审查：{len(llm_issues)} 项补充问题")
        for i in llm_issues[:3]:
            print(f"    [{i.get('level')}] {i.get('item')}（{i.get('standard', '')}）")
        all_issues += llm_issues
    except Exception as e:
        llm_issues = []
        print(f"③ LLM 审查跳过：{e}")
    history["review"] = {"rule": rule_issues, "step": step_problems, "llm": llm_issues}

    # ---------- 8. 优化报告 ----------
    banner(f"[8/8] {steps_meta['report']['title']}")
    report_path = write_report(case, spec, history, all_issues)
    total = time.time() - t_start
    print(f"✓ 优化报告已生成：{report_path}")
    print(f"\n⏱  全流程耗时：{total:.0f}s（预算 {meta['meta']['duration_sec']}s）")
    print("\n🎯 Demo 完成：自然语言 → 模型 → 工程图 → 三重审查 → 优化报告")
    return 0


def write_report(case: dict, spec: dict, history: dict, issues: list) -> str:
    """生成优化报告（Markdown）。"""
    from config import settings

    lines = ["# AI CAD Copilot 优化报告", ""]
    lines.append(f"- 案例：{case['name']}")
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 输入需求：{case['input']}")
    lines += ["", "## 1. 设计参数", ""]
    lines.append("```")
    lines.append(fmt_params(spec["params"]))
    lines.append("```")
    lines += ["", "## 2. 风险分析", ""]
    if not issues:
        lines.append("未发现明显问题。")
    else:
        lines.append("| 级别 | 来源 | 问题 | 建议 | 依据 |")
        lines.append("|---|---|---|---|---|")
        src_map = {}
        for i in history["review"]["rule"]:
            src_map[id(i)] = "规则"
        for i in history["review"]["step"]:
            src_map[id(i)] = "STEP"
        for i in history["review"]["llm"]:
            src_map[id(i)] = "LLM"
        for i in issues[:15]:
            lines.append(f"| {i.get('level') or i.get('risk')} | {src_map.get(id(i), '—')} | "
                         f"{i.get('item') or i.get('feature')} | {i.get('suggestion') or i.get('solution', '')} | "
                         f"{i.get('standard', '—')} |")
    lines += ["", "## 3. 修改建议", ""]
    for i in issues[:10]:
        lines.append(f"- **{i.get('item') or i.get('feature')}**：{i.get('suggestion') or i.get('solution', '')}")
    lines += ["", "## 4. 生成文件", ""]
    model = history.get("model", {})
    for key, p in (model.get("files") or {}).items():
        lines.append(f"- {key}: `{p}`")
    if history.get("drawing"):
        lines.append(f"- drawing.svg: `{history['drawing']}`")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = settings.get_reports_dir() / f"{stamp}_demo_{case['id']}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AI CAD Copilot 3 分钟 Demo")
    ap.add_argument("--http", type=int, default=0, help="HTTP 端口（0=模块内直连）")
    ap.add_argument("--case", type=int, default=0, help="案例序号（1=螺栓快速演示，2=电机轴工业级）")
    args = ap.parse_args()

    data = load_cases()
    if not (0 <= args.case < len(data["cases"])):
        print("可用案例：")
        for i, c in enumerate(data["cases"], 1):
            print(f"  [{i}] {c['name']}")
        sys.exit(1)
    case = data["cases"][args.case - 1] if args.case else data["cases"][0]
    print(f"\n>>> Demo 案例：{case['name']}\n")
    base = f"http://localhost:{args.http}" if args.http else None
    sys.exit(run(Client(base), case, args.case))
