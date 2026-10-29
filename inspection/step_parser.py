"""STEP 实体解析器：调用 FreeCAD(OpenCascade) 子进程解析 CAD 实体。

解析 CAD 实体：
    Solid / Face / Edge / Vertex 数量与结构
    Hole / Fillet / Chamfer / Slot / Thickness 特征
    特征位置（location）、内角（concave corners）

输出：原始解析结果（供 feature_detector / manufacturability_checker 使用）。
"""

import json
import logging
import os
import subprocess

from config import settings

log = logging.getLogger("inspection.step_parser")


def parse_step(step_path: str, out_dir: str | None = None) -> dict:
    """解析 STEP 文件，返回实体结构 + 特征原始数据。"""
    cmd = settings.find_freecad_cmd()
    if not cmd:
        raise RuntimeError("未找到 FreeCADCmd.exe，无法进行 STEP 解析")
    script = str(settings.SCRIPTS_DIR / "step_review.py")
    code = "exec(open({!r}, encoding='utf-8').read())".format(script)
    out_path = os.path.join(out_dir or str(settings.OUTPUT_DIR), "step_review_result.json")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]
    proc = subprocess.run(
        [cmd, "-c", code, "--pass", step_path, out_path],
        capture_output=True, text=True, timeout=300,
        encoding="utf-8", errors="replace", env=env,
        cwd=str(settings.ROOT_DIR),
    )
    if not os.path.isfile(out_path):
        raise RuntimeError("STEP 解析失败：" + (proc.stderr or proc.stdout or "")[-800:])
    with open(out_path, encoding="utf-8") as f:
        result = json.load(f)
    if not result.get("ok"):
        raise RuntimeError("STEP 解析异常：" + str(result.get("error", ""))[:500])
    result["source_step"] = step_path
    return result
