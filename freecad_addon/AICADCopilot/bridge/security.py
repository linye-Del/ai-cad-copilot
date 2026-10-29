"""Validation boundary for commands received by the FreeCAD Add-on."""

import os
import re
from urllib.parse import urlparse

ALLOWED_ACTIONS = {
    "create_document",
    "create_body",
    "create_sketch",
    "add_geometry",
    "add_constraint",
    "set_constraint",
    "create_pad",
    "create_revolution",
    "create_pocket",
    "create_additive_helix",
    "create_chamfer",
    "create_fillet",
    "create_pattern",
    "create_hole",
    "remove_fillet",
    "save_document",
    "create_techdraw",
    "validate_techdraw",
    "drawing_context",
    "export_techdraw_pdf",
    "create_box",
    "execute_plan",
    "inspect_document",
    "prepare_view",
    "capture_gui",
    "undo",
    "redo",
    "reopen_document",
    "use_active_document",
    "create_object",
    "inspect_object",
    "edit_object",
    "delete_object",
    "get_objects",
    "get_view",
}

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def validate_backend_url(url):
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Live FreeCAD bridge only accepts a localhost ws:// gateway")
    if not parsed.port:
        raise ValueError("Live FreeCAD bridge URL must include a port")
    return parsed.geturl()


def safe_name(value, fallback="Object"):
    value = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "")).strip("_")
    if not value:
        value = fallback
    if value[0].isdigit():
        value = "AI_" + value
    value = value[:64]
    if not _SAFE_NAME.fullmatch(value):
        raise ValueError("Invalid FreeCAD object name")
    return value


def validate_command(message):
    if not isinstance(message, dict):
        raise ValueError("Command must be an object")
    action = str(message.get("action", ""))
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported FreeCAD command: %s" % action)
    params = message.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("Command params must be an object")
    if len(str(message)) > 1024 * 1024:
        raise ValueError("Command payload is too large")
    return action, params


def validate_output_path(path, extensions):
    if not path:
        raise ValueError("Output path is required")
    full = os.path.abspath(os.path.expandvars(str(path)))
    if os.path.splitext(full)[1].lower() not in {e.lower() for e in extensions}:
        raise ValueError("Unsupported output file extension")
    if ".." in os.path.normpath(full).split(os.sep):
        raise ValueError("Invalid output path")
    return full
