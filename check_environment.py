"""AI CAD Copilot one-click startup environment check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from startup_common import environment_report  # noqa: E402


def _print_human(report: dict) -> None:
    python = report["python"]
    freecad = report["freecad"]
    dependencies = report["dependencies"]
    port = report["port"]
    addon = report["addon"]
    print("AI CAD Copilot 2.0 环境检查")
    print(f"[{'通过' if python['ok'] else '失败'}] Python {python['version']}  ({python['executable']})")
    if freecad["ok"]:
        print(f"[通过] FreeCAD {freecad['version'] or '版本未知'}  ({freecad['path']})")
    else:
        print("[失败] 未找到 FreeCAD GUI。请安装 FreeCAD，或在 .env 中设置 FREECAD_GUI。")
    if dependencies["ok"]:
        print(f"[通过] Python 依赖（{len(dependencies['installed'])} 项）")
    else:
        print("[失败] 缺少或版本不匹配的依赖：")
        for item in dependencies["missing"]:
            print(f"       - {item}")
        print("       请执行：python -m pip install -r requirements.txt")
    if port["state"] == "free":
        print(f"[通过] 端口 {port['number']} 可用")
    elif port["state"] == "aicad":
        print(f"[通过] AI CAD Backend 已在端口 {port['number']} 运行，将直接复用")
    else:
        print(f"[失败] 端口 {port['number']} 已被其他程序占用")
    print(f"[{'通过' if addon['source_exists'] else '失败'}] 插件源目录：{addon['source']}")
    print(f"[{'已安装' if addon['installed'] else '待安装'}] FreeCAD 插件：{addon['target']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 AI CAD Copilot 启动环境")
    parser.add_argument("--freecad", default="", help="FreeCAD.exe 的显式路径")
    parser.add_argument("--appdata", default="", help="覆盖 APPDATA（用于隔离测试）")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="发现问题时返回非零退出码")
    args = parser.parse_args()
    report = environment_report(args.freecad, args.appdata, args.port)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _print_human(report)
    port_ok = report["port"]["state"] in {"free", "aicad"}
    okay = report["ok"] and report["python"]["ok"] and report["addon"]["source_exists"] and port_ok
    return 0 if okay or not args.strict else 2


if __name__ == "__main__":
    raise SystemExit(main())
