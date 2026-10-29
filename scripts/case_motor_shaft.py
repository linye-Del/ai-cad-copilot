"""工业级案例：电机传动轴设计（examples/industrial_cases/motor_shaft）。

6 步流程：
  1. LLM 解析设计需求
  2. 根据机械规则推荐参数（扭转强度校核 → 轴段/轴承/键槽）
  3. 调用 FreeCAD MCP 生成参数化模型
  4. 自动生成工程图
  5. 执行 CAD 审查（决策系统规则 + STEP 模型审查 + LLM 深度审查）
  6. 输出设计报告

交付物（案例目录 examples/industrial_cases/motor_shaft/）：
  input.json      —— 输入需求定义
  design_report.md —— 设计报告（设计参数/风险分析/修改建议）
  model.FCStd     —— 三维模型
  drawing.svg     —— 工程图

用法：
    python scripts/case_motor_shaft.py --http 8000
"""

import io
import json
import math
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CASE_DIR = os.path.join(ROOT, "examples", "industrial_cases", "motor_shaft")
INPUT_PATH = os.path.join(CASE_DIR, "input.json")


def load_input() -> dict:
    with open(INPUT_PATH, encoding="utf-8") as f:
        return json.load(f)


def strength_calc(t_nm: float, tau_allow: float, weaken: float) -> dict:
    """扭转强度校核：计算满足 [τ] 的最小轴径。"""
    d_min = (16 * t_nm * 1000 / (math.pi * tau_allow)) ** (1 / 3)
    d_reco = math.ceil(d_min * weaken / 5) * 5  # 按 5mm 取整
    return {
        "torque_nm": t_nm,
        "tau_allow_mpa": tau_allow,
        "d_min_mm": round(d_min, 1),
        "d_recommend_mm": d_reco,
    }


def recommend_params(conf: dict) -> dict:
    """机械参数推荐：轴段分配（总长 300mm）、轴承、键槽、材料。"""
    req = conf["user_input"]["requirements"]
    dc = conf["design_constraints"]
    calc = strength_calc(req["torque_nm"], dc["torque_allow_stress_mpa"],
                         dc["keyway_weaken_factor"])
    d_end = calc["d_recommend_mm"]  # 45
    total = req["total_length_mm"]
    segs = [
        {"d": d_end, "L": 80},
        {"d": 45, "L": 45},
        {"d": 50, "L": total - 240},
        {"d": 45, "L": 45},
        {"d": d_end, "L": 60},
    ]
    return {
        "part_type": "shaft",
        "part_name": "500Nm电机传动轴",
        "params": {
            "segments": segs,
            "chamfer": dc.get("chamfer", 2.0),
            "fillet": dc.get("fillet", 1.5),
            # 联轴器端键槽（GB/T 1095，d45：键 14×9，轴槽深 t=5.5，键长 0.8×L）
            "keyway": {"enabled": True, "seg_index": 0, "w": 14, "t": 5.5, "lk": 63},
            "material": req["material"],
        },
        "strength": calc,
        "bearing": {"type": f"{dc['bearing_series']} 深沟球轴承", "d": 45, "D": 85, "B": 19,
                    "note": "d45 轴颈段配 6209（GB/T 276），轴肩 h≈2.5mm 定位内圈"},
        "coupling": {"type": dc["coupling_type"], "bore": 45,
                     "note": "d45 端配孔径 45 联轴器，键 14×9×63"},
    }


class Client:
    def __init__(self, base=None):
        if base:
            import requests
            self.base = base
            self.s = requests.Session()
        else:
            self.base = None

    def _req(self, method, path, body=None, timeout=600):
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


def run(client: Client) -> int:
    conf = load_input()
    case = conf["case"]
    req = conf["user_input"]
    torque = req["requirements"]["torque_nm"]
    print("=" * 72)
    print(f"工业级案例：{case['name']}")
    print(f"目标：{case['objective']}")
    print(f"输入：{req['text']}")
    print("=" * 72)

    report = {"case": case, "description": req["text"], "steps": {},
              "created": time.strftime("%Y-%m-%d %H:%M:%S")}

    # ---------- 1. LLM 解析设计需求 ----------
    print("\n[1/6] LLM 解析设计需求...")
    r = client._req("POST", "/api/parse", {"text": req["text"]}, timeout=180)
    spec = r["spec"]
    report["steps"]["parse"] = spec
    print(f"  识别: {spec['part_name']} | 来源: {spec['source']}")
    print(f"  提取参数: {json.dumps(spec['params'], ensure_ascii=False)[:300]}")

    # ---------- 2. 机械规则推荐参数 ----------
    print("\n[2/6] 机械规则推荐参数（扭转强度校核 + 标准件选型）...")
    reco = recommend_params(conf)
    calc = reco["strength"]
    print(f"  扭矩 T={torque}Nm, [τ]={calc['tau_allow_mpa']}MPa(45钢调质)")
    print(f"  最小轴径 d_min={calc['d_min_mm']}mm → 考虑键槽削弱取 d={calc['d_recommend_mm']}mm")
    print(f"  轴段: {reco['params']['segments']}")
    print(f"  轴承: {reco['bearing']['type']} | 联轴器: {reco['coupling']['type']}")
    report["steps"]["recommend"] = reco

    # ---------- 3. 调用 FreeCAD MCP 生成参数化模型 ----------
    print("\n[3/6] 调用 FreeCAD MCP 生成参数化模型...")
    sid = client._req("POST", "/api/sessions")["id"]
    r = client._req("POST", f"/api/sessions/{sid}/parts",
                    {"part_type": "shaft", "part_name": reco["part_name"],
                     "params": reco["params"]})
    print(f"  建模: {'OK' if r.get('ok') else 'FAIL'} retries={r.get('retries')} "
          f"文件={list(r.get('files', {}).keys())}")
    report["steps"]["model"] = r

    # ---------- 4. 自动生成工程图 ----------
    print("\n[4/6] 自动生成工程图...")
    r = client._req("POST", f"/api/sessions/{sid}/drawing")
    svg = r.get("drawing", {}).get("svg", "")
    print(f"  工程图: {'OK' if svg else 'FAIL'} svg={bool(svg)}")
    report["steps"]["drawing"] = r

    # ---------- 5. 执行 CAD 审查 ----------
    print("\n[5/6] 执行 CAD 审查（规则 + STEP + LLM）...")
    rule_issues, step_issues, llm_issues = [], [], []
    try:
        r = client._req("POST", f"/api/sessions/{sid}/validate", {"torque_nm": torque})
        rule_issues = r.get("issues", [])
        print(f"  ① 决策系统规则: {'通过' if r.get('passed') else f'{len(rule_issues)} 项'}")
        for i in rule_issues[:4]:
            print(f"    [{i['level']}] {i['item']}: {i['detail'][:55]}")
    except Exception as e:
        print(f"  ① 规则检查失败: {e}")
    try:
        r = client._req("POST", f"/api/sessions/{sid}/step-review", timeout=300)
        step_issues = r.get("problems", [])
        print(f"  ② STEP 模型审查: 面 {r['features']['faces']}，{len(step_issues)} 项问题")
    except Exception as e:
        print(f"  ② STEP 审查失败: {e}")
    try:
        r = client._req("POST", f"/api/sessions/{sid}/review", {"torque_nm": torque}, timeout=180)
        llm_issues = r.get("issues", [])
        print(f"  ③ LLM 深度审查: {len(llm_issues)} 项补充问题")
        for i in llm_issues[:3]:
            print(f"    [{i['level']}] {i['item']}（{i.get('standard', '')}）")
    except Exception as e:
        print(f"  ③ LLM 审查失败: {e}")
    report["steps"]["review"] = {"rule": rule_issues, "step": step_issues, "llm": llm_issues}

    # ---------- 6. 输出设计报告（含交付物落盘） ----------
    print("\n[6/6] 输出设计报告...")
    paths = _deliver(report, r_model=report["steps"]["model"], svg=svg)
    print(f"  ✓ design_report.md  → {paths['report']}")
    print(f"  ✓ model.FCStd       → {paths['model']}")
    print(f"  ✓ drawing.svg       → {paths['drawing']}")
    print("\n" + "=" * 72)
    print("工业级案例完成：LLM 解析 → 参数推荐 → MCP 建模 → 工程图 → CAD 审查 → 设计报告")
    print("=" * 72)
    return 0


def _deliver(report: dict, r_model: dict, svg: str) -> dict:
    """交付物落盘：design_report.md / model.FCStd / drawing.svg → 案例目录。"""
    from config import settings

    steps = report["steps"]
    reco = steps.get("recommend", {})

    # ---- design_report.md ----
    lines = [f"# {report['case']['name']} 设计报告", "",
             f"- 案例：{report['case']['name']}（{report['case']['industry']}）",
             f"- 生成时间：{report['created']}",
             f"- 输入需求：{report['description']}", ""]
    if reco:
        c = reco.get("strength", {})
        segs = reco.get("params", {}).get("segments", [])
        seg_txt = " / ".join(f"{s['d']}×{s['L']}" for s in segs)
        kw = reco.get("params", {}).get("keyway", {})
        kw_txt = (f"GB/T 1095 键 {kw.get('w', '')}×{round(kw.get('t', 0) + 3.5)}×{kw.get('lk', '')} "
                  f"(d{segs[0]['d']} 段) | 轴槽深 t={kw.get('t', '')}mm") if kw.get("enabled") else "无"
        lines += ["## 1. 设计参数", "",
                  "| 项目 | 数值 | 依据 |",
                  "|---|---|---|",
                  f"| 传递扭矩 T | {c.get('torque_nm')} N·m | 用户输入 |",
                  f"| 许用扭转应力 [τ] | {c.get('tau_allow_mpa')} MPa | 45钢调质 (GB/T 699) |",
                  f"| 最小轴径 d_min | {c.get('d_min_mm')} mm | τ=T/Wt 校核 |",
                  f"| 推荐轴端直径 | {c.get('d_recommend_mm')} mm | 键槽削弱系数 1.08 |",
                  f"| 轴段 (d×L) | {seg_txt} | 总长 {sum(s['L'] for s in segs)}mm |",
                  f"| 材料 | {reco.get('params', {}).get('material')} | 调质处理 217~255HBW |",
                  f"| 轴承 | {reco.get('bearing', {}).get('type')} | GB/T 276 |",
                  f"| 联轴器 | {reco.get('coupling', {}).get('type')} | 弹性柱销联轴器 |",
                  f"| 键槽 | {kw_txt} |", ""]

    review = steps.get("review", {})
    all_issues = review.get("rule", []) + review.get("step", []) + review.get("llm", [])
    lines += ["## 2. 风险分析", ""]
    if not all_issues:
        lines += ["未发现明显问题。"]
    else:
        lines += ["| 级别 | 来源 | 问题 | 描述 |", "|---|---|---|---|"]
        for i in all_issues:
            src = "规则" if i in review.get("rule", []) else \
                  ("STEP" if i in review.get("step", []) else "LLM")
            level = i.get("level") or i.get("risk") or "info"
            lines.append(f"| {level} | {src} | {i.get('item') or i.get('feature')} | "
                         f"{i.get('detail') or i.get('problem')} |")
    lines += ["", "## 3. 修改建议", ""]
    if not all_issues:
        lines += ["参数满足全部检查，可按图加工。"]
    else:
        for i in all_issues[:12]:
            lines.append(f"- **{i.get('item') or i.get('feature')}**："
                         f"{i.get('suggestion') or i.get('solution', '')}")
    lines += ["", "## 4. 交付物", "",
              "- `input.json`：输入需求定义",
              "- `model.FCStd`：三维模型（OpenCascade）",
              "- `drawing.svg`：工程图（三视图 + 尺寸标注）",
              "- `design_report.md`：本报告", ""]

    # ---- 落盘：案例目录（主）+ reports/（存档） ----
    os.makedirs(CASE_DIR, exist_ok=True)
    md_path = os.path.join(CASE_DIR, "design_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    model_path = ""
    for key in ("fcstd",):
        p = (r_model.get("files") or {}).get(key, "")
        if p and os.path.isfile(p):
            dst = os.path.join(CASE_DIR, "model.FCStd")
            shutil.copy(p, dst)
            model_path = dst
    drawing_path = ""
    if svg and os.path.isfile(svg):
        drawing_path = os.path.join(CASE_DIR, "drawing.svg")
        shutil.copy(svg, drawing_path)

    # reports/ 存档
    stamp = time.strftime("%Y%m%d_%H%M%S")
    report_dir = settings.get_reports_dir()
    (report_dir / f"{stamp}_motor_shaft_design.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": md_path, "model": model_path, "drawing": drawing_path}


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser(description="工业级案例：电机传动轴设计")
    ap.add_argument("--http", type=int, default=0, help="HTTP 端口（0=模块内直连）")
    args = ap.parse_args()
    base = f"http://localhost:{args.http}" if args.http else None
    sys.exit(run(Client(base)))
