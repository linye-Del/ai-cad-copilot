"""CAD 生成流程真实性验证。

目标：确认生成结果真实来自 FreeCAD（OpenCascade 实体），而非模拟/空/占位文件。

验证链路：
  1. 调用 FreeCAD MCP（REST → kernel → FreeCADCmd 子进程）创建真实 Part 对象
  2. 生成 Shape 并保存 .FCStd
  3. 导出 .step / .stl
  4. 用独立 FreeCAD 进程重新打开 .FCStd（从磁盘加载）验证：
     - 存在 Solid 实体
     - Volume > 0
     - Face 数量正常（> 0）
  5. 文件真实性：FCStd/STEP/STL 均非空（STEP/STL 含几何文本）

输出（每零件 + 汇总）：
    {"file": "", "solid": true, "volume": "", "faces": "", "valid": true}

用法：
    python scripts/cad_validation.py --http 8000 [--parts bolt,shaft,flange,gear]
"""

import io
import json
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PARTS = {
    "bolt": ("M10x40六角头螺栓", {"d": 10, "L": 40, "grade": "8.8"}),
    "shaft": ("三阶阶梯轴", {"segments": [{"d": 25, "L": 60}, {"d": 30, "L": 40}, {"d": 35, "L": 50}],
                              "chamfer": 1.0, "fillet": 1.0}),
    "flange": ("法兰盘D160", {"D": 160, "d": 50, "t": 18, "n": 8, "pcd": 130, "hole_d": 11, "chamfer": 2.0}),
    "gear": ("直齿圆柱齿轮", {"m": 2.5, "z": 20, "b": 25, "d_hub": 30}),
}

# STEP/STL 文件最小大小（真实几何文本远大于此，用于排除空文件）
MIN_STEP_SIZE = 1024
MIN_STL_SIZE = 1024
MIN_FCSTD_SIZE = 4096  # FCStd 为 zip 容器


def _request(base, method, path, body=None, timeout=600):
    import requests
    r = requests.request(method, base + path, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def validate_fcstd_on_disk(fcstd_path: str, work_dir: str) -> dict:
    """独立 FreeCAD 进程重新打开 FCStd，验证 Solid/Volume/Faces。"""
    from config import settings

    cmd = settings.find_freecad_cmd()
    script = str(settings.SCRIPTS_DIR / "validate_fcstd.py")
    code = "exec(open({!r}, encoding='utf-8').read())".format(script)
    out_path = os.path.join(work_dir, "fcstd_validation.json")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]
    proc = subprocess.run(
        [cmd, "-c", code, "--pass", fcstd_path, out_path],
        capture_output=True, text=True, timeout=300,
        encoding="utf-8", errors="replace", env=env, cwd=str(settings.ROOT_DIR),
    )
    if not os.path.isfile(out_path):
        raise RuntimeError("FCStd 重开验证失败：" + (proc.stderr or proc.stdout or "")[-500:])
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def check_file_real(path: str, min_size: int) -> tuple[bool, int]:
    """文件必须存在且大小超过阈值（排除空文件/占位文件）。"""
    if not os.path.isfile(path):
        return False, 0
    size = os.path.getsize(path)
    return size >= min_size, size


def validate_part(base: str, ptype: str, work_dir: str) -> dict:
    name, params = PARTS[ptype]
    result = {"part": ptype, "name": name, "steps": {}, "valid": False}

    # 1. 调用 FreeCAD MCP 创建零件
    t0 = time.time()
    sid = _request(base, "POST", "/api/sessions")["id"]
    r = _request(base, "POST", f"/api/sessions/{sid}/parts",
                 {"part_type": ptype, "part_name": name, "params": params})
    result["steps"]["mcp_create_part"] = {"ok": r.get("ok"), "retries": r.get("retries")}
    if not r.get("ok"):
        result["error"] = "MCP 建模失败"
        return result

    files = r.get("files", {})
    fcstd, step, stl = files.get("fcstd", ""), files.get("step", ""), files.get("stl", "")

    # 2~3. 文件存在且非空（排除空文件/占位输出）
    for key, path, min_size in (("fcstd", fcstd, MIN_FCSTD_SIZE),
                                ("step", step, MIN_STEP_SIZE),
                                ("stl", stl, MIN_STL_SIZE)):
        ok, size = check_file_real(path, min_size)
        result["steps"][f"file_{key}"] = {"exists": bool(path), "size_bytes": size,
                                          "non_empty": ok}
        if not ok:
            result["error"] = f"{key.upper()} 文件缺失或为空（{size} bytes）"
            return result

    # 4. 独立进程重新打开 FCStd 验证真实几何
    v = validate_fcstd_on_disk(fcstd, work_dir)
    result["steps"]["reopen_fcstd"] = v
    solid = bool(v.get("solids", 0) >= 1)
    volume = v.get("volume", 0.0)
    faces = v.get("faces", 0)
    valid = bool(v.get("ok")) and solid and volume > 0 and faces > 0

    result.update({
        "file": fcstd,
        "solid": solid,
        "volume": f"{volume} mm³",
        "faces": faces,
        "solids_count": v.get("solids", 0),
        "edges": v.get("edges", 0),
        "vertices": v.get("vertices", 0),
        "duration_s": round(time.time() - t0, 1),
        "valid": valid,
    })
    if not valid:
        result["error"] = f"FCStd 几何验证失败: solids={v.get('solids')} volume={volume} faces={faces}"
    return result


def main():
    import argparse
    ap = argparse.ArgumentParser(description="CAD 生成流程真实性验证")
    ap.add_argument("--http", type=int, default=8000)
    ap.add_argument("--parts", default="bolt,shaft,flange,gear",
                    help="逗号分隔的零件列表")
    args = ap.parse_args()

    base = f"http://localhost:{args.http}"
    work_dir = os.path.join(ROOT, "output", "cad_validation")
    os.makedirs(work_dir, exist_ok=True)

    results = []
    for ptype in [p.strip() for p in args.parts.split(",")]:
        print(f"▶ 验证 {ptype} ...")
        r = validate_part(base, ptype, work_dir)
        status = "✓ VALID" if r["valid"] else "✗ INVALID"
        print(f"  {status} | {r['file']}")
        print(f"  solid={r['solid']} volume={r.get('volume')} faces={r.get('faces')} "
              f"edges={r.get('edges')} vertices={r.get('vertices')} [{r.get('duration_s')}s]")
        results.append(r)

    all_valid = all(r["valid"] for r in results)
    summary = {"validated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "parts": results,
               "all_valid": all_valid,
               "count": len(results)}
    path = os.path.join(work_dir, "validation_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n{'='*60}")
    print(f"全部 {len(results)} 个零件 {'通过 ✓' if all_valid else '存在失败 ✗'}")
    print(f"验证报告: {path}")
    return 0 if all_valid else 1


if __name__ == "__main__":
    sys.exit(main())
