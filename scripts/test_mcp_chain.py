"""MCP stdio 客户端链测试：模拟 Agent 场景，观察 create_part 是否挂起。"""

import asyncio
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])


async def watch_freecad():
    """每 2 秒检查 freecadcmd 进程状态。"""
    import subprocess

    while True:
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq freecadcmd.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10).stdout
            lines = [l for l in out.strip().splitlines() if "freecadcmd" in l]
            if lines:
                for l in lines:
                    parts = l.split(",")
                    mem = parts[4].strip('"')
                    print(f"  [watch] freecadcmd pid={parts[1]} mem={mem}", flush=True)
            else:
                print("  [watch] no freecadcmd", flush=True)
        except Exception as e:
            print(f"  [watch] err {e}", flush=True)
        await asyncio.sleep(2)


async def main():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cad_engine.mcp_server.server"],
        cwd=ROOT,
        env=None,
    )
    watcher = asyncio.create_task(watch_freecad())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("工具数:", len(tools.tools), flush=True)

            r = await asyncio.wait_for(
                session.call_tool("create_session", {}), timeout=60)
            sid = r.content[0].text
            import json
            sid = json.loads(sid)["id"]
            print("create_session ->", sid, flush=True)

            print(">>> 开始 create_part (240s 超时)", flush=True)
            r = await asyncio.wait_for(
                session.call_tool("create_part", {
                    "session_id": sid,
                    "part_type": "bolt",
                    "part_name": "M10x40六角头螺栓",
                    "params": {"d": 10, "L": 40, "grade": "8.8"},
                }), timeout=240)
            print("create_part ->", r.content[0].text[:200], flush=True)
    watcher.cancel()


if __name__ == "__main__":
    asyncio.run(main())
