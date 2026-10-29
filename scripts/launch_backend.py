"""Start the Backend through an OS-owned host, never a launcher child."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if os.name == "nt":
        helper = project_root / "scripts" / "backend_task.ps1"
        command = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-Mode",
            "Start",
            "-ProjectRoot",
            str(project_root),
            "-Python",
            sys.executable,
            "-HostAddress",
            args.host,
            "-Port",
            str(args.port),
        ]
        completed = subprocess.run(
            command,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Windows Task Scheduler host registration failed: "
                + (completed.stderr or completed.stdout).strip()
            )
        lines = [line.strip().lstrip("\ufeff") for line in completed.stdout.splitlines()
                 if line.strip()]
        result = json.loads(lines[-1])
        result["command"] = subprocess.list2cmdline(command)
        result["detach_mode"] = "Windows Task Scheduler / on-demand / InteractiveToken"
        print(json.dumps(result, ensure_ascii=False))
        return 0

    command = [
        sys.executable,
        "-u",
        str(project_root / "scripts" / "backend_host.py"),
        "--project-root",
        str(project_root),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--host-mode",
        "posix-session",
        "--creation-flags",
        "start_new_session=True",
    ]
    process = subprocess.Popen(
        command,
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    print(json.dumps({
        "ok": True,
        "pid": process.pid,
        "detach_mode": "posix-session",
        "command": subprocess.list2cmdline(command),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
