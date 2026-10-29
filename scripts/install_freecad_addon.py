"""Install or atomically update the AI CAD Copilot FreeCAD Add-on."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from startup_common import addon_paths


IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
MANIFEST = ".aicad_install.json"


def source_files(source: Path) -> list[Path]:
    return sorted(
        path for path in source.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS for part in path.relative_to(source).parts)
        and path.suffix.lower() not in IGNORED_SUFFIXES
        and path.name != MANIFEST
    )


def tree_digest(source: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = source_files(source)
    for path in files:
        relative = path.relative_to(source).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def installed_digest(target: Path) -> str:
    manifest = target / MANIFEST
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("sha256", ""))
    except (OSError, ValueError, TypeError):
        return ""


def _validated_target(target: Path, appdata: str) -> Path:
    raw_appdata = appdata or os.getenv("APPDATA", "")
    if not raw_appdata:
        raise RuntimeError("无法确定 APPDATA，不能安装 FreeCAD 插件")
    appdata_root = Path(raw_appdata).expanduser().resolve()
    if not appdata_root.is_absolute():
        raise RuntimeError("APPDATA 不是绝对路径，不能安装 FreeCAD 插件")
    resolved = target.resolve()
    expected_parent = (appdata_root / "FreeCAD" / "Mod").resolve()
    if resolved.parent != expected_parent or resolved.name != "AICADCopilot":
        raise RuntimeError(f"拒绝写入非标准插件路径：{resolved}")
    return resolved


def install(appdata: str = "", force: bool = False) -> dict:
    source, target = addon_paths(appdata)
    if not source.is_dir() or not (source / "InitGui.py").is_file():
        raise RuntimeError(f"插件源目录不完整：{source}")
    target = _validated_target(target, appdata)
    digest, file_count = tree_digest(source)
    existed = target.is_dir()
    actual_digest = tree_digest(target)[0] if existed else ""
    if not force and existed and installed_digest(target) == digest and actual_digest == digest:
        return {"ok": True, "action": "unchanged", "target": str(target),
                "sha256": digest, "file_count": file_count}

    target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    stage = target.parent / f"AICADCopilot.new-{token}"
    backup = target.parent / f"AICADCopilot.old-{token}"
    shutil.copytree(source, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    (stage / MANIFEST).write_text(
        json.dumps({"sha256": digest, "file_count": file_count,
                    "source": str(source)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        if target.exists():
            target.rename(backup)
        stage.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if target.exists() and not (target / "InitGui.py").is_file():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.rename(target)
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"ok": True, "action": "updated" if existed else "installed",
            "target": str(target), "sha256": digest, "file_count": file_count}


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 AI CAD Copilot FreeCAD 插件")
    parser.add_argument("--appdata", default="", help="覆盖 APPDATA（用于隔离测试）")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = install(args.appdata, args.force)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif result["action"] == "unchanged":
            print(f"FreeCAD 插件已是最新版本：{result['target']}")
        else:
            print(f"FreeCAD 插件安装完成：{result['target']}")
        return 0
    except Exception as exc:
        print(f"FreeCAD 插件安装失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
