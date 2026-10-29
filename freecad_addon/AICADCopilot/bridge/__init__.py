"""Live backend bridge for the AI CAD Copilot Workbench.

Imports are intentionally lazy so native operation modules can be exercised in
FreeCAD console mode without loading the GUI WebSocket transport.
"""


def get_bridge():
    from AICADCopilot.bridge.client import get_bridge as _get_bridge
    return _get_bridge()


def start_bridge():
    from AICADCopilot.bridge.client import start_bridge as _start_bridge
    return _start_bridge()


__all__ = ["get_bridge", "start_bridge"]
