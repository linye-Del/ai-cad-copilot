# 开发指南

本文面向修改代码的贡献者。运行项目请先看 [installation.md](installation.md)。

## 1. 开发环境

```powershell
git clone https://github.com/linye-Del/ai-cad-copilot.git
cd ai-cad-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pytest
```

前端开发：

```powershell
cd frontend
npm ci
npm run dev      # Vite 开发服务器，默认 5173
```

生产构建：

```powershell
npm run build    # 输出到 frontend/dist，由 FastAPI 托管
```

## 2. 运行 Backend

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

- `--reload` 只用于开发；Live Bridge 连接在重载时会断开重连。
- 不要同时启动两个 Backend 占用 8000。
- 默认只监听 `127.0.0.1`；不要把开发服务暴露到公网。

## 3. 测试

```powershell
python -m pytest tests -q
```

当前测试覆盖：

| 文件 | 覆盖 |
|---|---|
| `test_api.py` | 健康检查、零件元数据、解析回退、会话 CRUD、FreeCADCmd 建模 |
| `test_live_agent.py` | 自然语言解析、PartSpec、CadPlan、原生特征、localhost 边界 |
| `test_drawing_layout.py` | 布局、比例、避碰、验证器 |
| `test_mechanical_drawing_rules.py` | 视图/尺寸选择规则 |
| `test_rules.py` / `test_decision_engine.py` | 决策规则、强度/材料/标准 |
| `test_tolerance.py` | 公差、配合、缺标 |
| `test_svg.py` | 程序化 SVG |
| `test_startup.py` | 启动器约束、计划任务、停止入口 |
| `test_upstream_adoption.py` | 第三方适配边界 |
| `test_inspection.py` | 可制造性检查的 import 回归 |

GUI 相关代码无法在无显示器 CI 中完整验证。修改 Live 路径时，必须额外提供真实 FreeCAD
GUI 的复现步骤、版本、截图和结果 JSON。

## 4. 目录结构

```text
backend/                 FastAPI、WebSocket gateway、静态前端
agent/                   Live Agent、schema、Legacy LangChain agent
knowledge_base/          设计策略、27 条规则、GB/T 数据
freecad_addon/           Workbench、bridge、原生操作、制图
inspection/              规则、STEP、公差、图纸一致性、可选 LLM
cad_engine/              Legacy FreeCADCmd 内核、零件库、MCP
frontend/                Vue 3 + Vite；dist 由 FastAPI 托管
scripts/                 安装、启动、验证、Demo、基准
tests/                   pytest
docs/                    安装、架构、故障、制图规则、验收记录
examples/                示例输入与交付物
```

## 5. 新增一个 Live 零件

以“带键槽轴”为例：

1. 在 `agent/live_schema.py` 扩展 `PartSpec`（或复用 `shaft` + `FeatureSpec`）。
2. 在 `knowledge_base/live_design.py` 增加设计策略，明确哪些尺寸是 user/standard/
   design_engine/assumption。
3. 在 `agent/live_agent.py` 的 `parse_live_request()` 和 `compile_cad_plan()` 增加解析与
   操作序列。
4. 如果使用已有 operation（`create_sketch`、`create_pocket` 等），优先复用；
   新 operation 必须同时修改：
   - `CadOperation.op` 字面量；
   - `freecad_addon/AICADCopilot/bridge/security.py` 白名单；
   - `freecad_addon/AICADCopilot/operations/` 执行器；
   - 测试。
5. 不允许在 CadPlan 中传递任意 Python 代码。
6. 增加单元测试 + 真实 GUI 验收记录。

## 6. 新增一条制图规则

- 视图/尺寸角色：`freecad_addon/AICADCopilot/drawing/rule_engine.py`
- 页面/比例/避碰：`layout_engine.py`
- 硬门槛：`validator.py`
- 说明文档：`docs/mechanical_drawing_rules.md`

修改后至少运行：

```powershell
python -m pytest tests\test_drawing_layout.py tests\test_mechanical_drawing_rules.py -q
```

如果规则依赖真实 TechDraw 投影，必须在 FreeCAD GUI 中复验，并保存页面截图/验证 JSON。

## 7. 新增审查规则

在 `knowledge_base/rules_data.py` 注册 `Rule`，提供：

- `condition`：何时触发；
- `analysis` / `cause`：工程机理；
- `consequence` / `risk`：风险；
- `recommendation`：可执行建议；
- `standard`：标准依据；
- `applies_to`：适用零件。

不要在规则中硬编码个人路径或外部服务凭据。新增规则要有正例/反例测试。

## 8. 前端开发注意事项

- `frontend/src/App.vue` 同时包含 Live 主路径和 Legacy 兼容区；不要把 Legacy 结果
  误标为 Live 成功。
- 修改后运行 `npm run build`，并提交更新后的 `frontend/dist`（项目为方便一键启动而
  附带预构建资源）。
- 不要提交 `node_modules`、Vite 缓存或 npm 日志。

## 9. 安全与隐私

- 不提交 `.env`、API Key、令牌、密码、代理凭据。
- 不在日志/截图/Issue 中暴露个人路径、用户名、桌面文件。
- 不执行用户提供的任意 Python；CadPlan 是白名单。
- 不把 Backend 暴露到公网；当前没有认证/多租户。
- 第三方代码必须保留许可证；参考/适配/依赖要区分，见 `THIRD_PARTY_NOTICES.md`。

## 10. 提交前检查

```powershell
python -m pytest tests -q
python -m compileall -q backend agent cad_engine inspection knowledge_base scripts
git diff --check
git status --short
```

确认没有 `.env`、日志、缓存、个人截图进入暂存区。提交信息使用 Conventional Commits，
例如：

```text
fix(inspection): 修复传入 features 时未导入 feature_detector
docs(readme): 增加中英双语发布说明与能力边界
```
