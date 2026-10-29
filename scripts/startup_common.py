"""Shared environment detection helpers for the one-click launcher."""

from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_file_value(name: str) -> str:
    path = PROJECT_ROOT / ".env"
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _as_freecad_gui(candidate: str | os.PathLike[str] | None) -> Path | None:
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if path.is_dir():
        for relative in ("FreeCAD.exe", "bin/FreeCAD.exe"):
            gui = path / relative
            if gui.is_file():
                return gui.resolve()
        return None
    if path.name.lower() == "freecadcmd.exe":
        path = path.with_name("FreeCAD.exe")
    return path.resolve() if path.is_file() and path.name.lower() == "freecad.exe" else None


def find_freecad_gui(explicit: str = "") -> str:
    """Locate the FreeCAD GUI, never choosing FreeCADCmd as the executor."""
    candidates: list[str | os.PathLike[str] | None] = [
        explicit,
        os.getenv("FREECAD_GUI"),
        os.getenv("FREECAD_BIN"),
        _env_file_value("FREECAD_GUI"),
        _env_file_value("FREECAD_BIN"),
        shutil.which("FreeCAD.exe"),
        Path("D:/applicant/bin/FreeCAD.exe"),
    ]
    program_files = [
        os.getenv("ProgramFiles", r"C:\Program Files"),
        os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.getenv("LOCALAPPDATA", ""),
    ]
    for base in filter(None, program_files):
        candidates.extend(sorted(glob.glob(str(Path(base) / "FreeCAD*" / "bin" / "FreeCAD.exe")), reverse=True))
        candidates.extend(sorted(glob.glob(str(Path(base) / "Programs" / "FreeCAD*" / "bin" / "FreeCAD.exe")), reverse=True))

    if os.name == "nt":
        try:
            import winreg

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for key_name in (
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\FreeCAD.exe",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\FreeCAD.exe",
                ):
                    try:
                        with winreg.OpenKey(hive, key_name) as key:
                            candidates.append(winreg.QueryValue(key, None))
                    except OSError:
                        pass
        except (ImportError, OSError):
            pass

    seen: set[str] = set()
    for candidate in candidates:
        gui = _as_freecad_gui(candidate)
        if gui is not None:
            normalized = os.path.normcase(str(gui))
            if normalized not in seen:
                return str(gui)
            seen.add(normalized)
    return ""


def freecad_version(gui_path: str) -> str:
    """Read the version using the sibling diagnostic binary when available."""
    if not gui_path:
        return ""
    gui = Path(gui_path)
    diagnostic = gui.with_name("FreeCADCmd.exe")
    command = diagnostic if diagnostic.is_file() else gui
    try:
        completed = subprocess.run(
            [str(command), "--version"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = (completed.stdout or completed.stderr).strip()
        return output.splitlines()[0].strip() if output else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def dependency_status() -> tuple[list[str], list[str]]:
    """Return (installed requirement names, missing/incompatible requirements)."""
    from importlib import metadata

    try:
        from packaging.requirements import Requirement
    except ImportError:
        return [], ["packaging（Python 环境不完整）"]

    installed: list[str] = []
    missing: list[str] = []
    requirements_path = PROJECT_ROOT / "requirements.txt"
    for raw in requirements_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
            version = metadata.version(requirement.name)
            if requirement.specifier and version not in requirement.specifier:
                missing.append(f"{line}（当前 {version}）")
            else:
                installed.append(f"{requirement.name}=={version}")
        except metadata.PackageNotFoundError:
            missing.append(line)
        except Exception as exc:
            missing.append(f"{line}（无法检查：{exc}）")
    return installed, missing


def backend_health(port: int = 8000, timeout: float = 0.8) -> dict:
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if (
            response.status == 200
            and payload.get("ok") is True
            and payload.get("service") == "ai-cad-copilot"
        ):
            return {"state": "aicad", "url": url, "payload": payload}
    except (OSError, ValueError, urllib.error.URLError):
        pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        occupied = probe.connect_ex(("127.0.0.1", port)) == 0
    return {"state": "occupied" if occupied else "free", "url": url, "payload": {}}


def addon_paths(appdata: str = "") -> tuple[Path, Path]:
    source = PROJECT_ROOT / "freecad_addon" / "AICADCopilot"
    raw_appdata = appdata or os.getenv("APPDATA", "")
    appdata_root = Path(raw_appdata).expanduser() if raw_appdata else None
    target = appdata_root / "FreeCAD" / "Mod" / "AICADCopilot" if appdata_root else Path()
    return source, target


def environment_report(freecad: str = "", appdata: str = "", port: int = 8000) -> dict:
    gui = find_freecad_gui(freecad)
    installed, missing = dependency_status()
    source, target = addon_paths(appdata)
    return {
        "ok": bool(gui) and not missing and bool(str(target)),
        "python": {
            "ok": sys.version_info >= (3, 10),
            "version": ".".join(str(x) for x in sys.version_info[:3]),
            "executable": sys.executable,
        },
        "freecad": {
            "ok": bool(gui),
            "path": gui,
            "version": freecad_version(gui),
        },
        "dependencies": {"ok": not missing, "installed": installed, "missing": missing},
        "port": {"number": port, **backend_health(port)},
        "addon": {
            "source": str(source),
            "target": str(target) if str(target) != "." else "",
            "source_exists": source.is_dir(),
            "installed": (target / "InitGui.py").is_file() if str(target) else False,
        },
    }
