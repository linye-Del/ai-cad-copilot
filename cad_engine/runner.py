"""调用 FreeCADCmd 无头执行建模+工程图脚本。"""

import json
import logging
import os
import re
import subprocess
import time

from config import settings

log = logging.getLogger("cad_engine.runner")


def find_freecad() -> str:
    return settings.find_freecad_cmd()


def cleanup_zombie_freecad(min_mem_kb: int = 50000):
    """清理残留的 freecadcmd 僵尸进程（FreeCAD 1.1 概率性挂起后残留，会阻塞后续启动）。

    FreeCAD 1.1 在异常退出后可能留下内存极小的僵尸进程，导致新实例初始化挂起。
    启动建模前自动清理内存占用极小的残留实例（保留正常运行的大内存实例）。
    """
    try:
        subprocess.run(
            ["taskkill", "/F", "/FI", f"MEMUSAGE lt {min_mem_kb}", "/IM", "freecadcmd.exe"],
            capture_output=True, timeout=20,
        )
    except Exception:
        pass


def _build_env(cmd: str, out_dir: str = None) -> dict:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]
    path = env.get("PATH", "")
    fc_bin = os.path.dirname(cmd)
    clean = [p for p in path.split(";") if p and not re.search(r"(?i)anaconda|conda|\\python", p)]
    env["PATH"] = fc_bin + ";" + ";".join(clean)
    env["FCC_REPO"] = str(settings.ROOT_DIR)
    if out_dir:
        user_home = os.path.join(out_dir, "fc_home")
    else:
        user_home = str(settings.OUTPUT_DIR / "fc_user_home")
    os.makedirs(user_home, exist_ok=True)
    env["FREECAD_USER_HOME"] = user_home
    return env


def run(spec: dict, out_dir: str = None, max_retries: int = 2) -> dict:
    cleanup_zombie_freecad()
    cmd = find_freecad()
    if not cmd:
        log.error("未找到 FreeCADCmd.exe（请配置 .env FREECAD_BIN 或 config.yaml freecad.bin）")
        raise RuntimeError(
            "未找到 FreeCADCmd.exe。请安装 FreeCAD 或在 .env 中设置 FREECAD_BIN，"
            "或运行 scripts/setup_freecad.ps1 自动安装。"
        )
    if not out_dir:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_dir = str(settings.OUTPUT_DIR / f"{stamp}_{spec['part_type']}")
    os.makedirs(out_dir, exist_ok=True)
    log.info("建模开始 part_type=%s part_name=%s out_dir=%s",
             spec.get("part_type"), spec.get("part_name"), out_dir)

    params_path = os.path.join(out_dir, "params.json")
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    script = str(settings.SCRIPTS_DIR / "run_fc.py")
    code = "exec(open({!r}, encoding='utf-8').read())".format(script)
    env = _build_env(cmd, out_dir)

    last_proc = None
    for attempt in range(max_retries + 1):
        last_proc = subprocess.run(
            [cmd, "-c", code, "--pass", params_path, out_dir],
            capture_output=True,
            stdin=subprocess.DEVNULL,  # MCP stdio 场景下 stdin 是协议管道，继承会导致 FreeCAD 初始化挂起
            text=True,
            timeout=900,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(settings.ROOT_DIR),
        )
        result_path = os.path.join(out_dir, "result.json")
        if os.path.isfile(result_path) and last_proc.returncode == 0:
            break
        time.sleep(2)

    result_path = os.path.join(out_dir, "result.json")
    if not os.path.isfile(result_path):
        tail = (last_proc.stderr or last_proc.stdout or "")[-3000:]
        log.error("FreeCAD 未生成结果文件 retries=%d rc=%s", attempt,
                  getattr(last_proc, "returncode", "?"))
        raise RuntimeError(f"FreeCAD 未生成结果文件。\n输出片段:\n{tail}")

    with open(result_path, encoding="utf-8") as f:
        result = json.load(f)
    result["out_dir"] = out_dir
    result["freecad_cmd"] = cmd
    result["freecad_log"] = (last_proc.stderr or "")[-3000:]
    result["retries"] = attempt
    _attach_svg(spec, out_dir, result)
    _attach_pdf(spec, out_dir, result)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info("建模完成 ok=%s retries=%d files=%s", result.get("ok"),
             result.get("retries"), list(result.get("files", {}).keys()))
    return result


def _attach_svg(spec: dict, out_dir: str, result: dict):
    """附加程序化 SVG 工程图预览（浏览器预览用，非最终工程图）。"""
    try:
        from cad_engine import drawing_svg

        svg_path = drawing_svg.render_file(spec, os.path.join(out_dir, "drawing.svg"))
        result.setdefault("drawing", {})["svg"] = svg_path
    except Exception:
        pass


def _attach_pdf(spec: dict, out_dir: str, result: dict):
    """附加标准工程图 PDF（TechDraw 真实数据 → 矢量渲染，最终工程图）。"""
    data_path = os.path.join(out_dir, "drawing_data.json")
    if not os.path.isfile(data_path):
        return
    try:
        from cad_engine import drawing_pdf

        pdf_path = os.path.join(out_dir, "drawing.pdf")
        drawing_pdf.render_from_data_file(data_path, pdf_path)
        if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 1000:
            result.setdefault("drawing", {})["pdf"] = pdf_path
    except Exception:
        log.exception("PDF 工程图渲染失败")