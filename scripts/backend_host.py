"""Long-lived Backend host with durable lifecycle diagnostics and shutdown."""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import platform
import signal
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class DurableLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def write(self, value: str) -> int:
        with self._lock:
            return self._stream.write(value)

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()

    def isatty(self) -> bool:
        return False

    def line(self, level: str, message: str) -> None:
        self.write(f"[{_stamp()}] [{level}] {message}\n")


def _windows_process_metadata() -> dict[str, object]:
    result: dict[str, object] = {
        "session_id": "n/a",
        "in_windows_job": False,
        "parent_path": "",
    }
    if os.name != "nt":
        return result
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_int)]
    kernel32.ProcessIdToSessionId.argtypes = [ctypes.c_ulong,
                                              ctypes.POINTER(ctypes.c_ulong)]
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                    ctypes.POINTER(ctypes.c_wchar),
                                                    ctypes.POINTER(ctypes.c_ulong)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    session_id = ctypes.c_ulong(0)
    if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
        result["session_id"] = int(session_id.value)
    in_job = ctypes.c_int(0)
    if kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(in_job)):
        result["in_windows_job"] = bool(in_job.value)
    parent = kernel32.OpenProcess(0x1000, False, os.getppid())
    if parent:
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(parent, 0, buffer, ctypes.byref(size)):
                result["parent_path"] = buffer.value
        finally:
            kernel32.CloseHandle(parent)
    return result


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--host-mode", default="direct")
    parser.add_argument("--task-name", default="")
    parser.add_argument("--creation-flags", default="")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    log_dir = project_root / "logs"
    log = DurableLog(log_dir / "backend.log")
    sys.stdout = log  # type: ignore[assignment]
    sys.stderr = log  # type: ignore[assignment]
    os.chdir(project_root)
    sys.path.insert(0, str(project_root))

    pid_path = log_dir / "backend.pid"
    lifecycle_path = log_dir / "backend.lifecycle.json"
    stop_path = log_dir / "backend.stop"
    started_wall = _stamp()
    started_monotonic = time.monotonic()
    process_metadata = _windows_process_metadata()
    shutdown = {"reason": "running", "signal": "", "exit_code": 1}
    finalized = {"done": False}
    stop_threads = threading.Event()

    previous_lifecycle: dict[str, object] = {}
    try:
        previous_lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        pass
    if previous_lifecycle.get("status") == "running":
        log.line(
            "WARNING",
            "上次Backend没有写入正常退出记录；推定为外部强制终止/Windows Job清理，"
            f"previous_pid={previous_lifecycle.get('pid')}",
        )

    try:
        stop_path.unlink()
    except FileNotFoundError:
        pass
    pid_path.write_text(str(os.getpid()), encoding="ascii")

    lifecycle_base: dict[str, object] = {
        "service": "ai-cad-copilot",
        "status": "running",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "parent_path": process_metadata["parent_path"],
        "session_id": process_metadata["session_id"],
        "in_windows_job": process_metadata["in_windows_job"],
        "host_mode": args.host_mode,
        "task_name": args.task_name,
        "creation_flags": args.creation_flags,
        "started_at": started_wall,
        "updated_at": started_wall,
        "uptime_seconds": 0.0,
        "shutdown_reason": "",
        "signal": "",
        "exit_code": None,
    }
    _write_json_atomic(lifecycle_path, lifecycle_base)

    command = (
        f'"{sys.executable}" -u "{Path(__file__).resolve()}" '
        f'--project-root "{project_root}" --host {args.host} --port {args.port}'
    )
    log.line("INFO", "===== AI CAD Copilot Backend host start =====")
    log.line("INFO", f"启动时间={started_wall}")
    log.line("INFO", f"Backend PID={os.getpid()}")
    log.line("INFO", f"Parent PID={os.getppid()}")
    log.line("INFO", f"Parent Path={process_metadata['parent_path']}")
    log.line("INFO", f"Session ID={process_metadata['session_id']}")
    log.line("INFO", f"Windows Job membership={process_metadata['in_windows_job']}")
    log.line("INFO", f"Host mode={args.host_mode}")
    log.line("INFO", f"Scheduled Task={args.task_name or 'n/a'}")
    log.line("INFO", f"Process creation flags={args.creation_flags or 'n/a'}")
    log.line("INFO", "stdin=TaskScheduler non-interactive; stdout/stderr=logs/backend.log")
    log.line("INFO", f"Python路径={sys.executable}")
    log.line("INFO", f"Python版本={platform.python_version()}")
    log.line("INFO", f"cwd={Path.cwd()}")
    log.line("INFO", f"uvicorn命令={command}")

    def finalize(reason: str, exit_code: int) -> None:
        if finalized["done"]:
            return
        finalized["done"] = True
        stop_threads.set()
        uptime = round(time.monotonic() - started_monotonic, 3)
        state = dict(lifecycle_base)
        state.update({
            "status": "stopped",
            "updated_at": _stamp(),
            "uptime_seconds": uptime,
            "shutdown_reason": reason,
            "signal": shutdown["signal"],
            "exit_code": exit_code,
        })
        try:
            _write_json_atomic(lifecycle_path, state)
        except OSError as exc:
            log.line("ERROR", f"生命周期文件写入失败={exc}")
        try:
            if pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid_path.unlink()
        except (FileNotFoundError, OSError):
            pass
        try:
            stop_path.unlink()
        except FileNotFoundError:
            pass
        log.line("INFO", f"Backend host exit，PID={os.getpid()}，exit_code={exit_code}，"
                           f"shutdown_reason={reason}，signal={shutdown['signal'] or 'none'}，"
                           f"uptime={uptime}s")

    atexit.register(lambda: finalize(str(shutdown["reason"]), int(shutdown["exit_code"])))
    server_holder: dict[str, object] = {}

    def note_signal(signum: int, _frame: object) -> None:
        shutdown["signal"] = str(signum)
        shutdown["reason"] = "os_signal"
        log.line("WARNING", f"收到终止信号={signum}，请求Uvicorn正常退出")
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True  # type: ignore[attr-defined]

    for signame in ("SIGTERM", "SIGBREAK", "SIGINT"):
        if hasattr(signal, signame):
            signal.signal(getattr(signal, signame), note_signal)

    def lifecycle_monitor() -> None:
        next_heartbeat = 30.0
        while not stop_threads.wait(0.5):
            uptime = time.monotonic() - started_monotonic
            if stop_path.exists():
                shutdown["reason"] = "stop_ai_cad_requested"
                log.line("INFO", "检测到 logs/backend.stop，开始正常关闭 Backend")
                server = server_holder.get("server")
                if server is not None:
                    server.should_exit = True  # type: ignore[attr-defined]
                return
            if uptime >= next_heartbeat:
                state = dict(lifecycle_base)
                state.update({"updated_at": _stamp(), "uptime_seconds": round(uptime, 3)})
                try:
                    _write_json_atomic(lifecycle_path, state)
                except OSError as exc:
                    log.line("ERROR", f"生命周期心跳写入失败={exc}")
                log.line("INFO", f"lifecycle heartbeat，uptime={round(uptime, 1)}s，"
                                   f"parent_pid={os.getppid()}，host_mode={args.host_mode}")
                next_heartbeat += 30.0

    threading.Thread(
        target=lifecycle_monitor, name="aicad-lifecycle", daemon=True
    ).start()

    try:
        from backend.main import app

        log.line("INFO", "import backend.main:app=成功")
        import uvicorn

        config = uvicorn.Config(app, host=args.host, port=args.port, access_log=False)
        server = uvicorn.Server(config)
        server_holder["server"] = server
        log.line("INFO", f"开始监听=http://{args.host}:{args.port}")
        server.run()
        if shutdown["reason"] == "running":
            shutdown["reason"] = "uvicorn_server_returned"
        shutdown["exit_code"] = 0
        return 0
    except KeyboardInterrupt:
        shutdown["reason"] = "keyboard_interrupt"
        shutdown["exit_code"] = 130
        log.line("WARNING", "Backend 被键盘中断")
        return 130
    except BaseException:
        shutdown["reason"] = "unhandled_exception"
        shutdown["exit_code"] = 1
        log.line("ERROR", "Backend 未处理异常，完整 traceback 如下：")
        traceback.print_exc(file=log)
        return 1
    finally:
        finalize(str(shutdown["reason"]), int(shutdown["exit_code"]))


if __name__ == "__main__":
    raise SystemExit(main())
