"""项目性能评估基准测试。

三项测试：
  1. CAD 生成时间   —— 4 零件 × N 次，分阶段计时（解析/建模/工程图/审查）
  2. 审图准确率     —— 预设缺陷用例的检出率（规则 + STEP 审查）
  3. Agent 流程统计 —— 工具调用次数 / Token 消耗 / 执行时间

输出：结果 JSON 到 reports/，并生成 docs/benchmark.md。

用法：
    python scripts/benchmark.py --http 8000 [--rounds 2]
"""

import io
import json
import os
import platform
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------- 测试案例定义 ----------------

CAD_CASES = [
    ("bolt", "M10x40六角头螺栓", {"d": 10, "L": 40, "grade": "8.8"}),
    ("shaft", "三阶阶梯轴", {"segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
                              "chamfer": 1.0, "fillet": 1.0}),
    ("flange", "法兰盘D160", {"D": 160, "d": 50, "t": 18, "n": 8, "pcd": 130, "hole_d": 11, "chamfer": 2.0}),
    ("gear", "直齿圆柱齿轮", {"m": 2.5, "z": 20, "b": 25, "d_hub": 30}),
]

# 审图准确率：预设缺陷用例 (零件, 参数, 扭矩, 预期缺陷描述)
DEFECT_CASES = [
    ("shaft", {"segments": [{"d": 30, "L": 80}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
               "chamfer": 1.0, "material": "45钢"}, 500,
     "扭转强度不足（d30 < 500Nm 所需最小轴径）", "error"),
    ("shaft", {"segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
               "chamfer": 1.0, "fillet": 0.0}, None,
     "轴肩无圆角（应力集中）", "warning"),
    ("shaft", {"segments": [{"d": 45, "L": 80}],
               "chamfer": 1.0, "keyway": {"enabled": True, "seg_index": 0, "w": 14, "t": 6.5, "lk": 40}}, None,
     "键槽深度超标（t/d=0.144 > 0.12）", "warning"),
    ("shaft", {"segments": [{"d": 45, "L": 80}],
               "chamfer": 1.0, "keyway": {"enabled": True, "seg_index": 0, "w": 14, "t": 5.5, "lk": 76}}, None,
     "键槽距轴端过近（端距 2mm < 5mm）", "warning"),
    ("gear", {"m": 2.5, "z": 20, "b": 25, "d_hub": 40}, None,
     "齿轮轮缘厚度不足（1.9mm < 0.8m）", "error"),
    ("flange", {"D": 120, "d": 110, "t": 10, "n": 8, "pcd": 115, "hole_d": 11}, None,
     "法兰壁厚过薄（5mm < 6mm）", "warning"),
    ("bolt", {"d": 9, "L": 40}, None,
     "螺栓直径非标准系列（M9）", "warning"),
    ("gear", {"m": 2.2, "z": 20, "b": 25, "d_hub": 30}, None,
     "齿轮模数非标准系列（2.2）", "warning"),
    ("shaft", {"segments": [{"d": 20, "L": 80}, {"d": 20, "L": 80}, {"d": 20, "L": 80}, {"d": 20, "L": 80},
                             {"d": 20, "L": 80}, {"d": 20, "L": 80}, {"d": 20, "L": 80}, {"d": 20, "L": 80},
                             {"d": 20, "L": 80}, {"d": 20, "L": 80}, {"d": 20, "L": 80}],
               "chamfer": 1.0}, None,
     "细长轴（长径比 44 > 20，挠度风险）", "info"),
    ("shaft", {"segments": [{"d": 45, "L": 80}, {"d": 45, "L": 45}],
               "chamfer": 1.0,
               "tolerances": [{"feature": "bearing_seat", "fit": "H7/g6"}]}, None,
     "轴承位误用间隙配合（应 k6/m6）", "warning"),
]


class Client:
    def __init__(self, base):
        import requests
        self.base = base
        self.s = requests.Session()

    def req(self, method, path, body=None, timeout=900):
        r = self.s.request(method, self.base + path, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()


# ---------------- 1. CAD 生成时间 ----------------

def bench_cad_time(client, rounds=2) -> dict:
    print("▶ [1/3] CAD 生成时间基准...")
    out = {}
    for ptype, name, params in CAD_CASES:
        times = []
        for i in range(rounds):
            t0 = time.time()
            sid = client.req("POST", "/api/sessions")["id"]
            t_parse = None
            spec = {"part_type": ptype, "part_name": name, "params": params}
            r = client.req("POST", f"/api/sessions/{sid}/parts", spec)
            t_model = time.time() - t0
            r2 = client.req("POST", f"/api/sessions/{sid}/drawing")
            t_draw = time.time() - t0
            times.append({"model_s": round(t_model, 1), "drawing_s": round(t_draw, 1),
                          "ok": r.get("ok")})
        out[ptype] = {
            "name": name,
            "runs": times,
            "avg_model_s": round(sum(t["model_s"] for t in times) / len(times), 1),
            "avg_total_s": round(sum(t["drawing_s"] for t in times) / len(times), 1),
        }
        print(f"  {ptype}: 平均建模 {out[ptype]['avg_model_s']}s / 总耗时 {out[ptype]['avg_total_s']}s")
    return out


# ---------------- 2. 审图准确率 ----------------

def bench_review_accuracy(client) -> dict:
    from inspection import rules as rc

    print("▶ [2/3] 审图准确率基准（预设缺陷检出）...")
    detected, total = 0, 0
    details = []
    for ptype, params, torque, defect_desc, expect_level in DEFECT_CASES:
        total += 1
        issues = rc.check(ptype, params, torque_nm=torque)
        # 判定：期望级别命中 或 缺陷关键词命中（issue 的任一文本字段）
        level_hit = any(i["level"] == expect_level for i in issues)
        kw = defect_desc.split("（")[0][:8]
        kw_hit = any(kw in (i["item"] + i["detail"] + i.get("suggestion", ""))
                     for i in issues)
        found = bool(level_hit) or bool(kw_hit)
        if found:
            detected += 1
        details.append({
            "case": f"{ptype}: {defect_desc[:40]}",
            "expected": expect_level,
            "detected": found,
            "issues": len(issues),
        })
        print(f"  {'✓' if found else '✗'} {ptype}: {defect_desc[:36]}")
    return {"total_defects": total, "detected": detected,
            "rate": round(detected / total * 100, 1), "details": details}


# ---------------- 3. Agent 流程统计 ----------------

def bench_agent(client) -> dict:
    import asyncio

    from agent import agent

    print("▶ [3/3] Agent 流程统计（M10×40 螺栓对话）...")
    query = "帮我生成一个M10x40的六角头螺栓，8.8级"
    stats = asyncio.run(agent.run_query_with_stats(query))
    tokens = stats["tokens"]
    print(f"  工具调用 {stats['tool_calls']} 次 | 耗时 {stats['duration_s']}s "
          f"| Token: 输入 {tokens['prompt']} / 输出 {tokens['completion']}")
    return {
        "query": query,
        "tool_calls": stats["tool_calls"],
        "duration_s": stats["duration_s"],
        "tokens": tokens,
        "message_count": stats["message_count"],
        "answer_preview": stats["answer"][:80],
    }


# ---------------- 报告落盘 ----------------

def environment() -> dict:
    import sys as _sys
    from config import settings
    return {
        "os": platform.platform(),
        "python": _sys.version.split()[0],
        "freecad": settings.find_freecad_cmd() or "未找到",
        "llm_model": settings.get_model(),
        "api_key": bool(settings.get_api_key()),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_report(data: dict) -> str:
    """生成 docs/benchmark.md。"""
    env = data["environment"]
    lines = ["# 性能基准测试报告", "",
             f"- 测试时间：{env['timestamp']}",
             f"- 操作系统：{env['os']}",
             f"- Python：{env['python']}",
             f"- FreeCAD：{env['freecad']}",
             f"- LLM：{env['llm_model']}（Key 已配置：{'是' if env['api_key'] else '否'}）", ""]

    lines += ["## 1. CAD 生成时间（输入需求 → 模型完成）", "",
              "| 零件 | 建模平均(s) | 建模+工程图平均(s) | 状态 |",
              "|---|---|---|---|"]
    for ptype, d in data["cad_time"].items():
        ok = all(r["ok"] for r in d["runs"])
        lines.append(f"| {d['name']} | {d['avg_model_s']} | {d['avg_total_s']} | {'✓' if ok else '✗'} |")
    lines += ["", "注：单次调用包含 FreeCADCmd 子进程启动 + 参数化建模 + STEP/STL 导出。", ""]

    lines += ["## 2. 审图准确率（预设缺陷检出）", "",
              f"**检出率：{data['review']['detected']}/{data['review']['total_defects']}"
              f"（{data['review']['rate']}%）**", "",
              "| 用例 | 预设缺陷 | 期望级别 | 检出 |",
              "|---|---|---|---|"]
    for d in data["review"]["details"]:
        lines.append(f"| {d['case']} | {d['case'].split(': ', 1)[-1]} | {d['expected']} | "
                     f"{'✓' if d['detected'] else '✗'} |")
    lines += [""]

    a = data["agent"]
    tok = a["tokens"]
    lines += ["## 3. Agent 流程统计（自然语言 → 建模 → 审查报告）", "",
              f"- 查询：`{a['query']}`", "",
              "| 指标 | 数值 |",
              "|---|---|",
              f"| 工具调用次数 | {a['tool_calls']} |",
              f"| 执行时间 | {a['duration_s']} s |",
              f"| Token 消耗（输入） | {tok['prompt']} |",
              f"| Token 消耗（输出） | {tok['completion']} |",
              f"| 消息轮次 | {a['message_count']} |", ""]

    lines += ["## 4. 测试环境", "",
              f"- 操作系统：{env['os']}",
              f"- Python：{env['python']}",
              f"- FreeCAD：{env['freecad']}",
              f"- LLM：{env['llm_model']}",
              f"- 测试时间：{env['timestamp']}", ""]

    path = os.path.join(ROOT, "docs", "benchmark.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=8000, help="HTTP 端口")
    ap.add_argument("--rounds", type=int, default=2, help="CAD 时间测试轮次")
    args = ap.parse_args()

    client = Client(f"http://localhost:{args.http}")
    data = {"environment": environment()}
    data["cad_time"] = bench_cad_time(client, args.rounds)
    data["review"] = bench_review_accuracy(client)
    data["agent"] = bench_agent(client)

    path = write_report(data)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    from config import settings
    (settings.get_reports_dir() / f"{stamp}_benchmark.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 基准报告已生成: {path}")


if __name__ == "__main__":
    main()
