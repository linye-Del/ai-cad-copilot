"""FreeCAD MCP Server：通过 MCP 协议向 LLM Agent 暴露 CAD 能力。"""

from .server import mcp

__all__ = ["mcp"]