"""Thread-safe dispatch state adapted from neka-nat/freecad-mcp (MIT)."""

import threading
import time


class DispatchHealth:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._task_id = ""
        self._operation = ""
        self._started_at = 0.0
        self._last_error = ""
        self._completed = 0

    def start(self, task_id, operation):
        with self._lock:
            self._task_id = str(task_id)
            self._operation = str(operation)
            self._started_at = self._clock()

    def finish(self, task_id, error=""):
        with self._lock:
            if self._task_id != str(task_id):
                return
            self._last_error = str(error or "")
            self._completed += 1
            self._task_id = ""
            self._operation = ""
            self._started_at = 0.0

    def snapshot(self, queued=0):
        with self._lock:
            elapsed = max(0.0, self._clock() - self._started_at) if self._task_id else 0.0
            return {"state": "busy" if self._task_id else "healthy",
                    "task_id": self._task_id, "operation": self._operation,
                    "running_for_seconds": round(elapsed, 3), "queued": int(queued),
                    "completed": self._completed, "last_error": self._last_error}

