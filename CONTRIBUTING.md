# 贡献指南

欢迎参与 AI CAD Copilot。提交前请先确认你遵守项目的许可证和安全边界。

## 1. 开发环境

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.10–3.12 | 后端、测试、脚本 |
| FreeCAD | 1.1.x | Live GUI 与 Legacy FreeCADCmd |
| Node.js | 18+ | 仅前端开发/构建 |
| pytest | 7+ | 测试 |
| DeepSeek Key | 可选 | 仅 Legacy LLM 解析和 LLM 审查 |

```powershell
git clone https://github.com/linye-Del/ai-cad-copilot.git
cd ai-cad-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install pytest
Copy-Item .env.example .env
```

**不要**把 `.env`、真实 Key、令牌、个人路径或含隐私的截图提交到仓库。

## 2. 运行与测试

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
python -m pytest tests -q
```

当前测试基线：**52 passed**（Windows + Python 3.12.7）。
GUI 相关变更必须额外提供真实 FreeCAD 版本、复现步骤和截图；单元测试不能代替 GUI 验收。

前端：

```powershell
cd frontend
npm ci
npm run build
```

## 3. 代码规范

- Python 遵循 PEP 8；优先类型注解。
- 中文注释可以，但标识符、日志键、API 字段使用英文。
- 不回显用户输入到日志中的敏感内容。
- 新增 CAD 操作必须：
  1. 进入 `CadOperation.op` 白名单；
  2. 进入 Add-on `security.py` 白名单；
  3. 有执行器、错误处理和测试；
  4. 不执行任意 Python。
- 新增第三方代码必须保留原许可证，并更新 `THIRD_PARTY_NOTICES.md`。
- 不要删除或改写已有的第三方许可证/版权声明。

## 4. 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```text
<type>(<scope>): <subject>
```

示例：

```text
fix(inspection): 修复传入 features 时未导入 feature_detector
feat(live): 增加带孔板 CadPlan 编译
docs(readme): 补充 Live 与 Legacy 的能力边界
test(drawing): 增加尺寸避碰回归
```

一个提交只做一件事；body 说明“为什么”。

## 5. Pull Request

请包含：

1. 变更目的与影响范围；
2. 复现步骤（FreeCAD 版本、输入、预期结果）；
3. 测试结果：`python -m pytest tests -q`；
4. 涉及 GUI 时附截图或结果 JSON；
5. 涉及许可证/第三方代码时说明来源与许可证；
6. 确认没有提交密钥、个人路径或临时产物。

CI 会在 Ubuntu 上运行 Python 测试；它不能替代 Windows + FreeCAD GUI 验收。

## 6. Issue

请使用 Issue 模板，并提供：

- 操作系统、Python、FreeCAD、Node 版本；
- 最小复现输入；
- 期望行为 vs 实际行为；
- `logs/backend.log`、`logs/freecad.log` 的相关片段（删除用户名、路径、Key）；
- 如果是 Live 问题，附 `/api/freecad/status` 返回。

安全漏洞请不要公开提交 Issue，使用 GitHub Security Advisory。

## 7. 模块入口

| 想做什么 | 看哪里 |
|---|---|
| 新 Live 零件 | `agent/live_schema.py`、`knowledge_base/live_design.py`、`agent/live_agent.py` |
| 新原生特征 | `freecad_addon/AICADCopilot/operations/` + `bridge/security.py` |
| 新制图规则 | `freecad_addon/AICADCopilot/drawing/rule_engine.py` |
| 新审查规则 | `knowledge_base/rules_data.py` |
| 新 REST 接口 | `backend/main.py` |
| 新 Legacy 零件 | `cad_engine/parts/` |
| 前端 | `frontend/src/App.vue` |

## 8. 许可证

提交即表示你同意以项目 MIT License 发布你的贡献，并确认你有权提交相关代码。
参考/适配第三方代码时，必须保留其许可证与版权声明；不确定时先开 Issue 讨论，不要直接合并。
