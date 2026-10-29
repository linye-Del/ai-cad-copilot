"""跨进程会话恢复测试：模拟 MCP 适配器每次工具调用新建子进程的行为。"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])

PROC_A = """
import sys
sys.path.insert(0, ROOT)
from cad_engine.mcp_server.kernel import kernel
s = kernel.create_session()
print(s.id)
"""

PROC_B = """
import json, sys
sys.path.insert(0, ROOT)
from cad_engine.mcp_server.kernel import kernel
r = kernel.create_part(SID, {"part_type": "bolt", "part_name": "M10x40六角头螺栓",
                             "params": {"d": 10, "L": 40, "grade": "8.8"}})
print(json.dumps({"ok": r.get("ok"), "files": list((r.get("files") or {}).keys()),
                  "svg": bool((r.get("drawing") or {}).get("svg"))}, ensure_ascii=False))
"""


def run(code):
    p = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=ROOT)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])
    return p.stdout.strip().splitlines()[-1]


if __name__ == "__main__":
    sid = run(PROC_A.replace("ROOT", repr(ROOT)))
    print("进程A create_session ->", sid)
    out = run(PROC_B.replace("ROOT", repr(ROOT)).replace("SID", repr(sid)))
    print("进程B create_part  ->", out)
    ok = json.loads(out)["ok"]
    print("跨进程会话恢复:", "PASS" if ok else "FAIL")
