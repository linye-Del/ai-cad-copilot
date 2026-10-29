# Demo 演示流程（求职展示）

## 方式一：Web 界面（推荐）

```bash
# 启动后端（默认 0.0.0.0:8000）
python -m uvicorn backend.main:app --port 8000

# 浏览器打开 http://localhost:8000
```

演示步骤：
1. 点击示例语句（螺栓/阶梯轴/法兰/齿轮）
2. 「解析参数」→ 查看 DeepSeek 识别的参数与派生尺寸
3. 「生成 3D 模型 + 工程图」→ 查看 SVG 工程图预览、下载 FCStd/STEP/STL
4. 「规则检查」→ GB/T 标准符合性
5. 「工程图审查」→ 标注与参数一致性
6. 「LLM 深度审查」→ 尺寸链/材料/工艺性深度复核

## 方式二：Agent 对话

```bash
# REST 接口（自然语言端到端，LLM→MCP→FreeCAD）
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"query": "帮我生成一个M10x40的六角头螺栓，8.8级"}'
```

## 方式三：Streamlit 单文件演示

```bash
streamlit run app.py
```

## 自动化回归

```bash
python scripts/e2e_test.py --http 8000   # 4 零件全链（解析/建模/规则/图纸/LLM 审查）
python scripts/test_crossproc.py         # 跨进程会话恢复
python scripts/test_mcp_chain.py         # MCP stdio 工具链
```
