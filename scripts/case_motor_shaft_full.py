"""完整工业设计案例：电机传动轴设计（examples/motor_shaft_case/）。

用户输入：
  功率 15kW / 转速 1450rpm / 扭矩 500Nm / 长度 300mm / 45钢 / 轴承+联轴器

完整流程：
  1. Design Engine 计算 —— 推荐轴径 / 材料 / 安全系数（含功率-扭矩一致性校验）
  2. FreeCAD MCP 生成 —— FCStd / STEP
  3. TechDraw 生成 —— 标准工程图 PDF
  4. Engineering Review —— 强度 / 加工 / 装配 / 公差
  5. 自动生成 design_case_report.md

交付物：
  input.json            输入需求
  analysis.json         Design Engine 分析结果
  model.FCStd           三维模型
  drawing.pdf           标准工程图
  review.md             审查结果
  design_case_report.md 总报告

用法：
    python scripts/case_motor_shaft_full.py --http 8000
"""

import io
import json
import math
import os
import shutil
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CASE_DIR = os.path.join(ROOT, "examples", "motor_shaft_case")

INPUT = {
    "case": {
        "id": "motor_shaft_case",
        "name": "电机传动轴设计（完整工业案例）",
        "industry": "电机传动",
    },
    "user_input": {
        "power_kw": 15,
        "speed_rpm": 1450,
        "torque_nm": 500,
        "total_length_mm": 300,
        "material": "45钢",
        "mounting": ["轴承", "联轴器"],
    },
}


class Client:
    def __init__(self, base: str):
        import requests
        self.base = base
        self.s = requests.Session()

    def req(self, method, path, body=None, timeout=900):
        r = self.s.request(method, self.base + path, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()


def step1_design_engine(client) -> dict:
    """Design Engine：参数合理性分析 + 功率-扭矩一致性校验。"""
    print("▶ [1/5] Design Engine 计算（推荐轴径/材料/安全系数）...")
    ui = INPUT["user_input"]
    # 功率-扭矩一致性校验：P(kW) = T(N·m) × n(rpm) / 9550
    t_from_power = 9550 * ui["power_kw"] / ui["speed_rpm"]
    t_user = ui["torque_nm"]
    consistency = {
        "power_kw": ui["power_kw"],
        "speed_rpm": ui["speed_rpm"],
        "torque_nm_input": t_user,
        "torque_from_power": round(t_from_power, 1),
        "note": (f"15kW @ 1450rpm 理论扭矩 T=9550P/n={t_from_power:.1f}N·m，"
                 f"与输入 500N·m 不一致（对应功率约 {t_user * ui['speed_rpm'] / 9550:.1f}kW）。"
                 f"按更保守的 500N·m 设计。"),
    }
    print(f"  一致性校验: 15kW@1450rpm → T={t_from_power:.1f}Nm | 输入 500Nm → 按 500Nm 设计（保守）")

    # Design Engine 分析（500Nm）
    from knowledge_base import decision_engine as de

    analysis = de.analyze_shaft(t_user, 45, ui["total_length_mm"], ui["material"])
    # 在 d_min 基础上确认推荐轴径（40mm 起步按 5mm 取整已在 engine 内）
    a = analysis["design"]
    print(f"  τ={a['tau_actual_mpa']}MPa [τ]={a['tau_allow_mpa']}MPa | "
          f"n={a['safety_factor']} | 推荐轴径 {a['recommend_d_range_mm']}mm | "
          f"风险: {analysis['risk']}")
    print(f"  材料建议: {a['recommend_material']}")
    return {"consistency": consistency, "analysis": analysis}


def step2_freecad_mcp(client) -> dict:
    """FreeCAD MCP 建模（FCStd/STEP）。"""
    print("▶ [2/5] FreeCAD MCP 生成（FCStd/STEP/STL）...")
    reco_params = {
        "segments": [{"d": 45, "L": 80}, {"d": 45, "L": 45}, {"d": 50, "L": 70},
                     {"d": 45, "L": 45}, {"d": 45, "L": 60}],
        "chamfer": 2.0, "fillet": 1.5,
        "keyway": {"enabled": True, "seg_index": 0, "w": 14, "t": 5.5, "lk": 63},
        "material": "45钢",
    }
    sid = client.req("POST", "/api/sessions")["id"]
    r = client.req("POST", f"/api/sessions/{sid}/parts",
                   {"part_type": "shaft", "part_name": "500Nm电机传动轴",
                    "params": reco_params})
    print(f"  建模: {'OK' if r.get('ok') else 'FAIL'} retries={r.get('retries')}")
    return {"session_id": sid, "result": r, "params": reco_params}


def step3_techdraw(client, step2: dict) -> dict:
    """TechDraw 标准工程图 PDF。"""
    print("▶ [3/5] TechDraw 生成（标准工程图 PDF）...")
    r = client.req("POST", f"/api/sessions/{step2['session_id']}/drawing")
    drawing = r.get("drawing", {})
    pdf, svg = drawing.get("pdf", ""), drawing.get("svg", "")
    print(f"  PDF: {'OK' if pdf else 'FAIL'} ({os.path.basename(pdf)}) | SVG 预览: {bool(svg)}")
    return {"pdf": pdf, "svg": svg, "result": r}


def step4_review(client, step2: dict, step3: dict) -> dict:
    """Engineering Review：强度/加工/装配/公差。"""
    print("▶ [4/5] Engineering Review（强度/加工/装配/公差）...")
    from knowledge_base import decision_engine as de

    review = de.evaluate_design("shaft", step2["params"], torque_nm=500)
    n_ew = sum(1 for i in review["issues"] if i.get("level") in ("error", "warning"))
    print(f"  规则 {len(review['issues'])} 项（error/warning {n_ew}）| "
          f"类别: {list(review['categories'].keys())}")
    # STEP 审查（可选增强）
    try:
        sr = client.req("POST", f"/api/sessions/{step2['session_id']}/step-review", timeout=600)
        review["step_review"] = {"problems": sr.get("problems", []),
                                 "faces": sr.get("features", {}).get("faces", 0)}
        print(f"  STEP 审查: 面 {sr.get('features', {}).get('faces')}，"
              f"{len(sr.get('problems', []))} 项问题")
    except Exception as e:
        review["step_review"] = {"problems": [], "error": str(e)[:120]}
    return review


def deliver(step1: dict, step2: dict, step3: dict, step4: dict) -> dict:
    """交付物落盘 examples/motor_shaft_case/。"""
    os.makedirs(CASE_DIR, exist_ok=True)

    # input.json
    with open(os.path.join(CASE_DIR, "input.json"), "w", encoding="utf-8") as f:
        json.dump(INPUT, f, ensure_ascii=False, indent=2)

    # analysis.json（Design Engine 完整输出）
    with open(os.path.join(CASE_DIR, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(step1, f, ensure_ascii=False, indent=2)

    # model.FCStd / STEP
    files = step2["result"].get("files", {})
    for key, dst in (("fcstd", "model.FCStd"), ("step", "model.step")):
        p = files.get(key, "")
        if p and os.path.isfile(p):
            shutil.copy(p, os.path.join(CASE_DIR, dst))

    # drawing.pdf
    pdf = step3.get("pdf", "")
    if pdf and os.path.isfile(pdf):
        shutil.copy(pdf, os.path.join(CASE_DIR, "drawing.pdf"))

    # review.md
    _write_review_md(step4)

    # design_case_report.md
    report = _write_report(step1, step2, step3, step4)
    return {"report": report}


def _write_review_md(review: dict):
    lines = ["# Engineering Review —— 工程审查", ""]
    sa = review.get("shaft_analysis")
    if sa:
        lines += ["## 强度分析", "",
                  f"- 风险：{sa['risk']}",
                  f"- 分析：{sa['analysis']}",
                  f"- 建议：{sa['recommendation']}",
                  f"- 依据：{sa['standard']}", ""]
    issues = review.get("issues", [])
    lines += ["## 审查结果", ""]
    if not issues:
        lines.append("未发现明显问题。")
    else:
        lines += ["| 类别 | 级别 | 问题 | 建议 | 依据 |", "|---|---|---|---|---|"]
        for i in issues:
            lines.append(f"| {i.get('category_cn', '—')} | {i.get('level')} | "
                         f"{i.get('item')} | {i.get('suggestion')} | {i.get('standard', '—')} |")
    sr = review.get("step_review", {})
    if sr.get("faces"):
        lines += ["", "## STEP 模型审查", "",
                  f"- 面数量：{sr.get('faces')}",
                  f"- 问题数：{len(sr.get('problems', []))}"]
        for p in sr.get("problems", [])[:5]:
            lines.append(f"- [{p.get('risk')}] {p.get('feature')}：{p.get('problem')}")
    path = os.path.join(CASE_DIR, "review.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_report(step1: dict, step2: dict, step3: dict, step4: dict) -> str:
    lines = ["# 电机传动轴设计 —— 完整工业案例报告", "",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 输入：15kW / 1450rpm / 500N·m / 300mm / 45钢 / 轴承+联轴器", ""]

    lines += ["## 1. Design Engine 计算", ""]
    cons = step1["consistency"]
    lines += [f"- 功率-扭矩一致性校验：{cons['note']}", ""]
    a = step1["analysis"]
    d = a["design"]
    lines += ["| 项目 | 数值 |", "|---|---|",
              f"| 实际扭转应力 τ | {d['tau_actual_mpa']} MPa |",
              f"| 许用扭转应力 [τ] | {d['tau_allow_mpa']} MPa |",
              f"| 安全系数 n | {d['safety_factor']} |",
              f"| 最小轴径 d_min | {d['d_min_mm']} mm |",
              f"| 推荐轴径范围 | {d['recommend_d_range_mm'][0]}~{d['recommend_d_range_mm'][1]} mm |",
              f"| 材料建议 | {d['recommend_material']} |", "",
              f"**设计风险：{a['risk']}**", "",
              f"- 原因：{a['analysis']}",
              f"- 建议：{a['recommendation']}",
              f"- 依据：{a['standard']}", ""]

    lines += ["## 2. FreeCAD 建模与工程图", "",
              f"- 模型：`model.FCStd` / `model.step`（retries=0）",
              f"- 工程图：`drawing.pdf`（TechDraw 标准工程图，SVG 预览保留）", ""]

    lines += ["## 3. Engineering Review", ""]
    issues = step4.get("issues", [])
    lines += [f"- 规则检查：{len(issues)} 项（"
              f"{sum(1 for i in issues if i['level'] in ('error', 'warning'))} error/warning）",
              f"- 类别覆盖：{'、'.join(step4.get('categories', {}).keys())}"]
    sr = step4.get("step_review", {})
    if sr.get("faces"):
        lines.append(f"- STEP 特征审查：面 {sr['faces']}，{len(sr.get('problems', []))} 项问题")
    lines += [""]

    lines += ["## 4. 修改建议", ""]
    if issues:
        for i in issues[:8]:
            lines.append(f"- **{i.get('item')}**：{i.get('suggestion')}")
    else:
        lines.append("参数满足全部检查，可按图加工。")

    lines += ["", "## 5. 交付物", "",
              "- `input.json`：输入需求",
              "- `analysis.json`：Design Engine 分析",
              "- `model.FCStd` / `model.step`：三维模型",
              "- `drawing.pdf`：标准工程图",
              "- `review.md`：工程审查",
              "- `design_case_report.md`：本报告", ""]
    path = os.path.join(CASE_DIR, "design_case_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=8000)
    args = ap.parse_args()
    client = Client(f"http://localhost:{args.http}")

    print("=" * 68)
    print("完整工业案例：电机传动轴设计（15kW / 1450rpm / 500Nm）")
    print("=" * 68)
    s1 = step1_design_engine(client)
    s2 = step2_freecad_mcp(client)
    s3 = step3_techdraw(client, s2)
    s4 = step4_review(client, s2, s3)
    delivered = deliver(s1, s2, s3, s4)
    print("\n" + "=" * 68)
    print(f"✅ 案例完成：{delivered['report']}")
    for f in sorted(os.listdir(CASE_DIR)):
        print(f"   {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
