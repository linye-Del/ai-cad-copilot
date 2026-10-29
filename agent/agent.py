"""LLM Agent 层：LangChain + DeepSeek，通过 MCP 协议连接 FreeCAD Server。"""

import logging
import os

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import settings

log = logging.getLogger("agent")

SYSTEM_PROMPT = """你是资深机械设计工程师，负责把用户的中文需求转换为 CAD 建模操作并做质量把关。

工作流程：
1. 先用 list_part_types 查看可用零件类型与参数字段；
2. 创建会话 create_session；
3. 调用 create_part 建模（参数必须符合 GB/T 标准系列，如模数、螺栓直径）；
4. 建模成功后调用 make_drawing 生成工程图；
5. 调用 validate_part 做规则审查，若有 error/warning 级别问题，用中文向用户说明并建议修正；
6. 汇总输出（必须给出具体数值，不要留空或写"见上"）：
   - 零件信息：零件名称、类型、材料、性能等级/精度
   - 关键尺寸列表：如 d、L、b、模数、齿数、外径、总长等，每项一行「名称 = 数值 mm」
   - 生成文件清单：FCStd/STEP/STL/SVG 的完整 Windows 路径，每行一个
   - 审查结论：通过/存在问题的级别与条目

注意事项：
- 用户描述含糊时（如"大一点的螺栓"），先问清关键参数，不要臆测；
- 尺寸一律以毫米(mm)为单位；
- 输出文件路径以反斜杠 Windows 路径为准，直接返回给用户即可。
"""

_mcp_adapter = None
_agent = None


def _ensure_adapter():
    global _mcp_adapter
    if _mcp_adapter is None:
        _mcp_adapter = MultiServerMCPClient(
            {
                "freecad": {
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-m", "cad_engine.mcp_server.server"],
                    "cwd": str(settings.ROOT_DIR),
                    "env": {**os.environ, "PYTHONPATH": str(settings.ROOT_DIR)},
                }
            }
        )
    return _mcp_adapter


async def get_agent():
    """创建（或复用）ReAct Agent。异步获取 MCP 工具，仅首次调用时连接。"""
    global _agent
    if _agent is None:
        _agent = await _build_agent()
    return _agent


async def _build_agent():
    api_key = settings.get_api_key()
    if not api_key:
        log.error("未配置 DEEPSEEK_API_KEY")
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在项目根目录 .env 中设置")
    llm = ChatOpenAI(
        base_url=settings.get_api_base(),
        api_key=api_key,
        model=settings.get_model(),
        temperature=settings.get_llm_temperature(),
        timeout=settings.get_llm_timeout(),
    )
    adapter = _ensure_adapter()
    tools = await adapter.get_tools()
    log.info("Agent 构建完成，MCP 工具 %d 个", len(tools))
    return create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )


async def run_query(query: str) -> str:
    """执行用户查询，返回最终回复文本。"""
    stats = await run_query_with_stats(query)
    return stats["answer"]


async def run_query_with_stats(query: str) -> dict:
    """执行用户查询并采集流程统计（工具调用/Token/耗时），供基准测试使用。"""
    import time

    from langchain_core.callbacks import BaseCallbackHandler

    class _UsageCollector(BaseCallbackHandler):
        def __init__(self):
            self.tokens = {"prompt": 0, "completion": 0}

        def on_llm_end(self, response, **kwargs):
            # langchain-openai：usage 在 llm_output.token_usage（非流式）
            usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
            if not usage:
                for gen in response.generations:
                    info = (gen[0].generation_info or {}) if gen else {}
                    usage = info.get("token_usage") or {}
                    if usage:
                        break
            self.tokens["prompt"] += usage.get("prompt_tokens", 0)
            self.tokens["completion"] += usage.get("completion_tokens", 0)

    collector = _UsageCollector()
    agent = await get_agent()
    log.info("Agent 执行查询: %s", query[:80])
    t0 = time.time()
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": query}]},
        config={"recursion_limit": settings.get_agent_recursion_limit(),
                "callbacks": [collector]},
    )
    duration = round(time.time() - t0, 1)
    messages = result["messages"]
    tool_calls = sum(1 for m in messages if getattr(m, "type", "") == "tool")
    answer = messages[-1].content
    log.info("Agent 完成，工具调用 %d 次，耗时 %.1fs", tool_calls, duration)
    return {
        "answer": answer,
        "tool_calls": tool_calls,
        "duration_s": duration,
        "tokens": collector.tokens,
        "message_count": len(messages),
    }


async def close():
    global _mcp_adapter, _agent
    # langchain-mcp-adapters 0.3.2 无显式 close：释放引用，子进程随 Python 退出终止
    _mcp_adapter = None
    _agent = None