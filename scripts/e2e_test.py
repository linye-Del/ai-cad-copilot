"""端到端集成测试：REST 全链路（解析 → 建模 → 工程图 → 三重审查）。

用法：
    python scripts/e2e_test.py                # 直连模块级测试（不需启动服务）
    python scripts/e2e_test.py --http 8000    # 通过 HTTP 测试已运行的服务
"""

import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PARTS = [
    ("bolt", "M10x40六角头螺栓", {"d": 10, "L": 40, "grade": "8.8"}),
    ("shaft", "三阶阶梯轴", {"segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}], "chamfer": 1.0, "fillet": 1.0}),
    ("flange", "法兰盘D160", {"D": 160, "d": 50, "t": 18, "n": 8, "pcd": 130, "hole_d": 11, "chamfer": 2.0}),
    ("gear", "直齿圆柱齿轮", {"m": 2.5, "z": 20, "b": 25, "d_hub": 30}),
]

PROMPTS = [
    "生成一个M10×40的六角头螺栓，8.8级，螺纹长度25mm，材料40Cr",
    "做一个阶梯轴：直径25×60、30×40、35×50，末端倒角C1",
    "设计法兰盘：外径160mm，内径50mm，厚度18mm，8个螺栓孔，分度圆130mm",
    "直齿圆柱齿轮：模数2.5，齿数20，齿宽25mm，孔径30mm",
]


class Client:
    def __init__(self, base=None):
        if base:
            import requests
            self.base = base
            self.s = requests.Session()
        else:
            self.base = None

    def _req(self, method, path, body=None):
        if self.base:
            r = self.s.request(method, self.base + path, json=body, timeout=600)
            r.raise_for_status()
            return r.json()
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app) as c:
            r = c.request(method, path, json=body)
            r.raise_for_status()
            return r.json()


def run(client: Client):
    ok_all = True
    results = []
    for i, (ptype, name, params) in enumerate(PARTS):
        print(f"\n{'='*60}\n[{i+1}/{len(PARTS)}] {name} ({ptype})")
        t0 = time.time()
        steps = {}

        # 1. 自然语言解析
        r = client._req("POST", "/api/parse", {"text": PROMPTS[i]})
        spec = r["spec"]
        steps["parse"] = spec["part_type"] == ptype
        print(f"  解析: {spec['part_name']} ({spec['source']})")

        # 2. 创建会话 + 建模
        sid = client._req("POST", "/api/sessions")["id"]
        r = client._req("POST", f"/api/sessions/{sid}/parts",
                        {"part_type": ptype, "part_name": name, "params": params})
        steps["model"] = bool(r.get("ok"))
        files = list((r.get("files") or {}).keys())
        print(f"  建模: {'OK' if r.get('ok') else 'FAIL'} 文件={files} retries={r.get('retries')}")

        # 3. 规则检查
        r = client._req("POST", f"/api/sessions/{sid}/validate")
        steps["validate"] = r.get("passed")
        n_issues = len(r.get("issues", []))
        print(f"  规则检查: {'通过' if r.get('passed') else f'{n_issues} 项问题'}")

        # 4. 工程图审查
        try:
            r = client._req("POST", f"/api/sessions/{sid}/drawing-review")
            steps["drawing_review"] = r.get("passed")
            print(f"  工程图审查: {'通过' if r.get('passed') else '有问题'}")
        except Exception as e:
            steps["drawing_review"] = False
            print(f"  工程图审查: 失败 {e}")

        # 5. LLM 深度审查
        try:
            r = client._req("POST", f"/api/sessions/{sid}/review")
            steps["llm_review"] = "issues" in r
            print(f"  LLM 深度审查: {len(r.get('issues', []))} 项补充问题")
        except Exception as e:
            steps["llm_review"] = False
            print(f"  LLM 深度审查: 失败 {e}")

        passed = all(steps.values())
        ok_all &= passed
        results.append({"part": name, "passed": passed, "steps": steps, "time_s": round(time.time() - t0)})

    print(f"\n{'='*60}\n汇总:")
    for r in results:
        print(f"  {r['part']}: {'PASS' if r['passed'] else 'FAIL'} {r['time_s']}s "
              f"{[k for k, v in r['steps'].items() if not v] or ''}")
    print(f"\n总体: {'全部通过' if ok_all else '存在失败'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=0, help="HTTP 端口（0=模块内直连测试）")
    args = ap.parse_args()
    base = f"http://localhost:{args.http}" if args.http else None
    sys.exit(run(Client(base)))
