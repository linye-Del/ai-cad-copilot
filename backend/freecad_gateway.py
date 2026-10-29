"""Live FreeCAD WebSocket gateway.

The FreeCAD Add-on connects to this gateway from the running GUI process.  The
gateway intentionally knows nothing about the existing headless CAD pipeline;
it only tracks the live connection and forwards small, typed commands.
"""

from __future__ import annotations

import asyncio
from collections import deque
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class FreeCADOfflineError(RuntimeError):
    """Raised when a live FreeCAD instance is not connected."""


class FreeCADCommandError(RuntimeError):
    """Raised when the Add-on rejects or fails a command."""


class FreeCADGateway:
    """Track one live FreeCAD GUI instance and dispatch request/response RPC."""

    def __init__(self, stale_after: float = 15.0):
        self.stale_after = stale_after
        self._websocket: WebSocket | None = None
        self._instance: dict[str, Any] = {}
        self._last_seen = 0.0
        self._pending: dict[str, asyncio.Future] = {}
        self._send_lock = asyncio.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=100)

    def status(self) -> dict[str, Any]:
        connected = (
            self._websocket is not None
            and self._last_seen > 0
            and time.monotonic() - self._last_seen <= self.stale_after
        )
        return {
            "freecad_online": connected,
            "status": "connected" if connected else "disconnected",
            "instance_id": self._instance.get("instance_id", "") if connected else "",
            "freecad_version": self._instance.get("freecad_version", "") if connected else "",
            "active_document": self._instance.get("active_document", "") if connected else "",
            "active_object": self._instance.get("active_object", "") if connected else "",
            "object_count": self._instance.get("object_count", 0) if connected else 0,
            "active_workbench": self._instance.get("active_workbench", "") if connected else "",
            "workbench_registered": self._instance.get("workbench_registered", False) if connected else False,
            "dock_visible": self._instance.get("dock_visible", False) if connected else False,
            "model_tree_visible": self._instance.get("model_tree_visible", False) if connected else False,
            "dock_widgets": self._instance.get("dock_widgets", []) if connected else [],
            "gui_dispatch": self._instance.get("gui_dispatch", {}) if connected else {},
            "active_modal": self._instance.get("active_modal", "") if connected else "",
            "last_seen": self._instance.get("reported_at", "") if connected else "",
            "last_event": self._events[-1] if self._events else None,
        }

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        previous = self._websocket
        self._websocket = websocket
        self._instance = {}
        self._events.clear()
        self._last_seen = time.monotonic()
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=1012, reason="FreeCAD instance replaced")
            except Exception:
                pass

        try:
            while True:
                message = await websocket.receive_json()
                await self._handle_message(websocket, message)
        except WebSocketDisconnect:
            pass
        finally:
            if self._websocket is websocket:
                self._disconnect("FreeCAD connection closed")

    async def _handle_message(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind in {"hello", "register", "status", "heartbeat"}:
            self._last_seen = time.monotonic()
            self._instance.update(
                {
                    "instance_id": message.get("instance_id", ""),
                    "freecad_version": message.get("freecad_version", ""),
                    "active_document": message.get("active_document", ""),
                    "active_object": message.get("active_object", ""),
                    "object_count": message.get("object_count", 0),
                    "active_workbench": message.get("active_workbench", ""),
                    "workbench_registered": message.get("workbench_registered", False),
                    "dock_visible": message.get("dock_visible", False),
                    "model_tree_visible": message.get("model_tree_visible", False),
                    "dock_widgets": message.get("dock_widgets", []),
                    "gui_dispatch": message.get("gui_dispatch", {}),
                    "active_modal": message.get("active_modal", ""),
                    "reported_at": message.get("reported_at", ""),
                }
            )
            if kind in {"hello", "register"}:
                await self._send_json(
                    {"type": "hello_ack", "freecad_online": True, "gateway": "AI CAD Copilot"}
                )
            return

        if kind in {"command_result", "response"}:
            self._last_seen = time.monotonic()
            for field in (
                "active_document", "active_object", "object_count",
                "active_workbench", "workbench_registered", "dock_visible",
                "model_tree_visible", "reported_at",
                "dock_widgets",
                "gui_dispatch",
                "active_modal",
            ):
                if field in message:
                    self._instance[field] = message.get(field)
            request_id = str(message.get("request_id", ""))
            future = self._pending.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(message)
            return

        if kind == "event":
            self._last_seen = time.monotonic()
            self._events.append(message)
            return

        if kind == "user_query":
            query = str(message.get("query", "")).strip()
            if query:
                asyncio.create_task(self._run_user_query(query))

    async def execute(self, action: str, params: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        if not self.status()["freecad_online"] or self._websocket is None:
            raise FreeCADOfflineError("FreeCAD 未连接，请先启动 FreeCAD 和 AI CAD Copilot 插件")

        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._send_json(
                {
                    "type": "command",
                    "request_id": request_id,
                    "action": action,
                    "params": params,
                }
            )
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise FreeCADCommandError(f"FreeCAD 命令超时: {action}") from exc
        finally:
            self._pending.pop(request_id, None)

        if not response.get("ok"):
            raise FreeCADCommandError(response.get("error") or f"FreeCAD 命令失败: {action}")
        return response.get("result") or {}

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._websocket is None:
            raise FreeCADOfflineError("FreeCAD connection closed")
        async with self._send_lock:
            await self._websocket.send_json(payload)

    async def _run_user_query(self, query: str) -> None:
        try:
            from agent.live_agent import run_live_query

            result = await run_live_query(query)
            payload = {"type": "agent_message", "ok": True,
                       "message": result.get("message", "Live CAD operation completed"),
                       "result": result}
        except Exception as exc:
            payload = {"type": "agent_message", "ok": False,
                       "message": str(exc), "error": str(exc)}
        try:
            await self._send_json(payload)
        except Exception:
            pass

    def _disconnect(self, reason: str) -> None:
        self._websocket = None
        self._instance = {}
        self._last_seen = 0.0
        for future in self._pending.values():
            if not future.done():
                future.set_exception(FreeCADOfflineError(reason))
        self._pending.clear()


gateway = FreeCADGateway()
