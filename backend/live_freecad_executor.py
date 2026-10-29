"""Backend-side executor for the running FreeCAD GUI instance.

This class never imports FreeCAD and never calls ``FreeCADCmd``.  It forwards
typed commands to the Add-on registered with :mod:`backend.freecad_gateway`.
"""

from typing import Any

from backend.freecad_gateway import gateway


class LiveFreeCADExecutor:
    async def status(self) -> dict[str, Any]:
        return gateway.status()

    async def execute_operation(self, operation: str, **params) -> dict[str, Any]:
        return await gateway.execute(operation, params, timeout=30.0)

    async def execute_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return await gateway.execute("execute_plan", {"plan": plan}, timeout=180.0)

    async def inspect_document(self) -> dict[str, Any]:
        return await gateway.execute("inspect_document", {}, timeout=20.0)

    async def create_object(self, **params) -> dict[str, Any]:
        return await gateway.execute("create_object", params, timeout=30.0)

    async def inspect_object(self, name: str) -> dict[str, Any]:
        return await gateway.execute("inspect_object", {"name": name}, timeout=20.0)

    async def edit_object(self, name: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await gateway.execute(
            "edit_object", {"name": name, "properties": properties}, timeout=30.0)

    async def delete_object(self, name: str, force: bool = False) -> dict[str, Any]:
        return await gateway.execute(
            "delete_object", {"name": name, "force": force}, timeout=30.0)

    async def get_objects(self, all_properties: bool = False) -> dict[str, Any]:
        return await gateway.execute(
            "get_objects", {"all_properties": all_properties}, timeout=20.0)

    async def get_view(self, view_name: str = "Isometric", **params) -> dict[str, Any]:
        return await gateway.execute(
            "get_view", {"view_name": view_name, **params}, timeout=30.0)

    async def prepare_view(self, mode: str = "model", page: str = "") -> dict[str, Any]:
        params = {"mode": mode}
        if page:
            params["page"] = page
        return await gateway.execute("prepare_view", params, timeout=20.0)

    async def capture_gui(self, path: str) -> dict[str, Any]:
        return await gateway.execute("capture_gui", {"path": path}, timeout=30.0)

    async def undo(self) -> dict[str, Any]:
        return await gateway.execute("undo", {}, timeout=30.0)

    async def redo(self) -> dict[str, Any]:
        return await gateway.execute("redo", {}, timeout=30.0)

    async def reopen_document(self, path: str) -> dict[str, Any]:
        return await gateway.execute("reopen_document", {"path": path}, timeout=60.0)


live_executor = LiveFreeCADExecutor()
