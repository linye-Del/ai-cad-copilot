"""One-click launcher helpers must remain deterministic and safe."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from install_freecad_addon import MANIFEST, install  # noqa: E402
from startup_common import _as_freecad_gui, addon_paths  # noqa: E402


def test_freecad_cmd_path_is_normalized_to_gui(tmp_path):
    gui = tmp_path / "FreeCAD.exe"
    cmd = tmp_path / "FreeCADCmd.exe"
    gui.write_bytes(b"")
    cmd.write_bytes(b"")
    assert _as_freecad_gui(cmd) == gui.resolve()


def test_addon_installer_is_incremental_and_uses_standard_target(tmp_path):
    appdata = tmp_path / "Roaming"
    first = install(str(appdata))
    second = install(str(appdata))
    source, target = addon_paths(str(appdata))

    assert first["action"] == "installed"
    assert second["action"] == "unchanged"
    assert target == appdata / "FreeCAD" / "Mod" / "AICADCopilot"
    assert (target / "InitGui.py").is_file()
    manifest = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["sha256"] == first["sha256"]
    assert manifest["file_count"] == len([
        path for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ])


def test_backend_host_records_required_lifecycle_diagnostics():
    source = (ROOT / "scripts" / "backend_host.py").read_text(encoding="utf-8")
    for marker in (
        "启动时间=", "Backend PID=", "Python路径=", "cwd=",
        "uvicorn命令=", "import backend.main:app=成功", "traceback",
        "Parent PID=", "Session ID=", "Windows Job membership=",
        "shutdown_reason=", "uptime=", "backend.lifecycle.json",
    ):
        assert marker in source

    launcher = (ROOT / "scripts" / "launch_backend.py").read_text(encoding="utf-8")
    assert "backend_task.ps1" in launcher
    assert "Windows Task Scheduler" in launcher
    assert "CREATE_BREAKAWAY_FROM_JOB" not in launcher


def test_user_stop_and_long_lived_validation_use_public_entrypoints():
    stop = (ROOT / "stop_ai_cad.ps1").read_text(encoding="utf-8-sig")
    assert "backend.stop" in stop
    assert "api/health" in stop
    assert "CloseMainWindow" in stop
    assert "stop.log" in stop
    assert "scripts\\backend_host.py" in stop

    validation = (ROOT / "scripts" / "validate_user_launch.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "start_ai_cad.bat" in validation
    assert "backend_host.py" not in validation
    assert "launch_backend.py" not in validation
    assert "direct_uvicorn_used = $false" in validation
    for checkpoint in ("0, 30, 60, 300, 900", "launcher_exit_proved"):
        assert checkpoint in validation


def test_scheduled_task_prevents_duplicate_backend_instances():
    source = (ROOT / "scripts" / "backend_task.ps1").read_text(encoding="utf-8-sig")
    assert "TASK_INSTANCES_IGNORE_NEW" in source
    assert "Windows Task Scheduler Service" in source
    assert "TASK_LOGON_INTERACTIVE_TOKEN" in source
    assert "TASK_TRIGGER_LOGON" in source
    assert 'RestartCount = 3' in source
    assert 'StopOnIdleEnd = $false' in source
    assert "config-version=" in source


def test_launcher_requires_listener_health_and_website_before_freecad():
    source = (ROOT / "start_ai_cad.ps1").read_text(encoding="utf-8-sig")
    listener = source.index("Get-ListeningPid")
    health = source.index("Backend OK")
    website = source.index("Website Ready")
    freecad = source.index('Write-Step "启动 FreeCAD GUI"')
    browser = source.index('Write-Step "打开 AI 聊天入口"')

    assert listener < health < website < freecad < browser
    assert "BackendTimeoutSeconds = 60" in source
    assert 'Join-Path $logDir "backend.log"' in source
    assert "Get-BackendFailureReport" in source
    assert "计划任务提前停止" in source
    assert "正在准备后台服务" in source
