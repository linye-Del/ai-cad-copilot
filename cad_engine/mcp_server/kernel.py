"""会话管理 + FreeCADCmd 子进程内核桥。

每个会话对应 output/sessions/{id}/ 目录，零件文件与工程图保存在其中。
FreeCAD 在独立子进程中执行，崩溃不影响服务进程；失败自动重试。
"""

import json
import logging
import os
import time
import uuid

from config import settings
from cad_engine import runner

log = logging.getLogger("cad_engine.kernel")


class Session:
    def __init__(self, sid: str):
        self.id = sid
        self.dir = str(settings.OUTPUT_DIR / "sessions" / sid)
        self.created = time.time()
        self.last_active = self.created
        os.makedirs(self.dir, exist_ok=True)

    @property
    def fcstd(self) -> str:
        hits = [f for f in os.listdir(self.dir) if f.endswith(".FCStd")]
        return os.path.join(self.dir, hits[0]) if hits else ""

    def touch(self):
        self.last_active = time.time()

    def state(self) -> dict:
        return {
            "id": self.id,
            "dir": self.dir,
            "created": self.created,
            "last_active": self.last_active,
            "fcstd": self.fcstd,
            "files": sorted(os.listdir(self.dir)),
        }


class Kernel:
    """管理 FreeCAD 会话并调度子进程执行建模任务。"""

    def __init__(self, ttl: float | None = None):
        self.sessions: dict[str, Session] = {}
        self.ttl = ttl if ttl is not None else float(settings.get("output", "sessions_ttl_sec", 7200))

    def _gc(self):
        now = time.time()
        for sid in list(self.sessions):
            if now - self.sessions[sid].last_active > self.ttl:
                del self.sessions[sid]

    def create_session(self) -> Session:
        self._gc()
        sid = uuid.uuid4().hex[:12]
        s = Session(sid)
        self.sessions[sid] = s
        log.info("会话创建 %s", sid)
        return s

    def get_session(self, sid: str) -> Session:
        self._gc()
        if sid not in self.sessions:
            # 从磁盘恢复：MCP 适配器每次工具调用会新建子进程，内存态会话会丢失，
            # 但只要 output/sessions/{id}/ 目录存在即可恢复（目录创建于 create_session）。
            sdir = settings.OUTPUT_DIR / "sessions" / sid
            if sdir.is_dir():
                s = Session(sid)
                self.sessions[sid] = s
            else:
                raise KeyError(f"会话不存在或已过期: {sid}")
        s = self.sessions[sid]
        s.touch()
        return s

    def close_session(self, sid: str) -> bool:
        return self.sessions.pop(sid, None) is not None

    def list_sessions(self) -> list[dict]:
        self._gc()
        return [s.state() for s in self.sessions.values()]

    def create_part(self, sid: str, spec: dict) -> dict:
        s = self.get_session(sid)
        result = runner.run(spec, out_dir=s.dir)
        return {"session_id": sid, **result}

    def make_drawing(self, sid: str) -> dict:
        s = self.get_session(sid)
        if not s.fcstd:
            raise ValueError("会话中还没有零件文件，请先调用 create_part")
        spec = self._last_spec(s)
        r = runner.run(spec, out_dir=s.dir)
        return {"session_id": sid, **r}

    def _last_spec(self, s: Session) -> dict:
        path = os.path.join(s.dir, "params.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


kernel = Kernel()