# GitHub 发布审计

审计日期：2026-10-29（Asia/Shanghai）  
正式项目：`E:\ai cad\a-cad-copilot`  
目标仓库：`https://github.com/linye-Del/ai-cad-copilot`  
审计结论：**代码与文档已具备公开发布条件；仓库创建/认证/推送是当时未完成的发布阻断项。**
（本文是发布前快照，最终推送结果见 [github_release_report.md](github_release_report.md)。）

## 1. 审计范围与方法

- 检查 E 盘正式项目的目录、入口、依赖、测试、文档、Git 状态与历史。
- 与 D 盘旧副本做逐文件 SHA-256 对比，不把 D 盘直接覆盖 E 盘。
- 实际启动 Backend，检查 `/api/health`、首页、`/api/part-types`、`/api/freecad/status`。
- 运行 52 个 Python 测试；运行 Vite 生产构建；用 FreeCADCmd 做建模冒烟。
- 扫描工作区与 Git 对象中的高熵密钥模式，检查个人路径和敏感文档。
- 检查许可证、第三方适配代码与 AGPL 依赖。
- 检查 GitHub 目标地址、远程、认证与仓库是否存在。

## 2. E 盘与 D 盘差异

| 项目 | 值 |
|---|---|
| E 盘正式目录 | `E:\ai cad\a-cad-copilot` |
| D 盘旧副本 | `D:\ChatGPT\New project\a-cad-copilot` |
| 对比方法 | 排除 `.git`、`node_modules`、`__pycache__`、缓存、`output/`、`logs/`、`reports/`、`tmp/`、`work/`、`.freecad_gui/`、`frontend/dist/`、`.env` 后逐文件 SHA-256 |
| 共同文件 | 195 |
| 内容不同的共同文件 | **0** |
| 仅 E 盘存在 | 26 |
| 仅 D 盘存在 | 3 |
| 结论 | 两份代码没有“D 比 E 更新”的功能差异；E 盘是正式版本，D 是旧工作副本 |

### 仅 D 盘存在的文件

| 文件 | 判断 | 处理 |
|---|---|---|
| `docs/drawing_layout_validation.md` | 有价值的制图布局验收记录 | 已合并到 E 盘，并清理日期/路径表述 |
| `docs/screenshots/startup/pre_cold_start_desktop.png` | 空白桌面截图，无证据价值 | 不合并 |
| `docs/screenshots/startup/website_connected.png` | 旧版网页连接截图，E 有更新的 `website_connected_final.png` | 不合并 |

D 盘还有 `.freecad_gui/`（个人 FreeCAD 配置）、`tmp/`（PDF 临时图）、`work/accept_freecad_save.ps1`
（含硬编码 E 盘路径的 UI 自动化脚本）。这些是个人/临时文件，**没有**合并到正式项目，也不应公开。

### 仅 E 盘存在的主要文件

| 类别 | 例子 | 公开处理 |
|---|---|---|
| 最新 GUI/启动截图 | `docs/screenshots/live/*`、`startup/*`、`upstream/*` | 只挑选无个人路径的截图公开；其余保留本地 |
| 生成产物 | `examples/demo/model.FCStd`、`drawing.svg`、`industrial_cases/motor_shaft/*` | 作为演示证据保留/筛选，不把运行目录整体提交 |
| 前端构建 | `frontend/dist/*` | 为保证一键启动可复现，纳入公开仓库 |
| 本地配置 | `.env` | **不提交**，只保留 `.env.example` |

## 3. 正式发布版本与路径

- 正式版本：`E:\ai cad\a-cad-copilot`
- 公开版本号：`v0.2.0`（public preview；不是把旧的本地 `v1.0.0` 标签伪装成稳定版）
- 公开分支：`main`（由经过审计的快照创建；旧 `master` 历史仅保留在本地）
- 代码基线：E 盘工作区，包含 2.0 Live Agent、制图布局/校验、检查规则与启动脚本
- 不覆盖 D 盘，不把 D 盘的个人配置、临时文件、路径脚本带入公开历史

## 4. 核心模块清单与真实状态

| 模块 | 真实状态 | 证据/边界 |
|---|---|---|
| FastAPI Backend | 已实现且本次启动验证 | `/api/health`、首页、`/api/part-types`、`/api/freecad/status` 可访问 |
| Vue 3 前端 | 已实现且构建验证 | `npm ci && npm run build` 成功；`dist` 由 FastAPI 托管 |
| FreeCAD Add-on / Workbench | 已实现，历史 GUI 验证 | 27 个源文件；Dock/Workbench/Bridge 有历史截图 |
| Live FreeCAD Bridge | 已实现，历史 GUI 验证 | localhost WebSocket、心跳、命令队列、重连；本次 GUI 未重新拉起 |
| AI Agent | 双路径 | Live 为确定性解析 + Design Engine；Legacy 为 LangChain/MCP + 可选 LLM |
| Design Engine | 已实现并测试 | 阶梯轴/螺栓/法兰/带孔板的尺寸策略与假设记录 |
| PartSpec / CadPlan | 已实现并测试 | Pydantic 强类型；操作白名单；来源标记 |
| 原生参数化建模 | 已实现，历史 GUI 验证 | Body/Sketch/Pad/Pocket/AdditiveHelix/Chamfer/Fillet |
| TechDraw 工程图 | 已实现，历史 GUI 验证 | 同一 Document 的页面/视图/关联尺寸/PDF |
| DrawingLayoutEngine | 已实现并测试 | 页面、比例、安全区、避碰 |
| DrawingValidator | 已实现并测试 | 越界、比例、重叠、必需尺寸、关联尺寸等硬门槛 |
| MechanicalDrawingRuleEngine | 已实现并测试 | 按轴/法兰/板/螺栓选择必需视图与尺寸角色 |
| 一键启动/停止 | 已实现，历史验证 | Windows 启动器 + 用户级计划任务；手动流程已文档化 |
| 测试 | 已实现且本次通过 | **52 passed**（Windows + Python 3.12.7） |
| 示例/截图/发布记录 | 已整理 | 示例 JSON/FCStd/STEP/PDF；真实 GUI 截图；本审计/报告 |

### 明确未实现或未完整验证

- 任意拓扑自动规划：无。
- 精确渐开线齿轮：仅 Legacy 简化齿形。
- 装配、干涉、FEA、图纸 OCR：无。
- 完整 GD&T、粗糙度、焊接符号、BOM、剖视/局部放大自动生成：无。
- 第二台干净 Windows 机器的 FreeCAD GUI 复验：本次未完成。
- macOS/Linux 一键启动：无；Backend 可手动跨平台运行。

## 5. 本次实际验证结果

| 检查 | 结果 |
|---|---|
| Python 测试 | **52 passed** |
| 前端生产构建 | 成功（Vite，输出 `frontend/dist`） |
| Backend 启动 | 成功，HTTP 200 |
| 首页 HTML | 成功，引用构建后的 JS/CSS |
| `/api/part-types` | 成功，UTF-8 中文正常 |
| `/api/freecad/status` | 正常返回 `freecad_online=false`（未启动 GUI） |
| Legacy FreeCADCmd 建模 | 测试中通过（bolt FCStd/STEP/STL） |
| Live GUI | 本次未成功重新拉起（GUI 进程提前退出）；历史验收记录保留 |
| 干净目录复现 | 发布后执行；见最终报告 |

> 说明：测试套件中的 2 个 `tmp_path` 用例在受限文件沙箱下曾报 `PermissionError`；
> 在项目目录的完整权限下全量运行 **52 passed**。这不是项目代码失败。

## 6. 已知问题

| 问题 | 影响 | 处理 |
|---|---|---|
| Live GUI 本次未复验 | 不能声称“今天在干净 GUI 环境通过” | README/报告明确标注历史证据；不伪造通过 |
| PyMuPDF 是 AGPL-3.0/商业双许可 | 默认依赖会带来许可证义务 | 已从 `requirements.txt` 移除；改为 `requirements-pdf.txt` opt-in；增加错误提示 |
| `manufacturability_checker` 在传入 features 时缺少 `feature_detector` 导入 | 特定 STEP 审查会 `NameError` | 已修复并增加 `tests/test_inspection.py` |
| 两个测试脚本硬编码 `E:\...` | 其他机器无法运行 | 已改为根据 `__file__` 推导根目录 |
| 冷启动验证脚本硬编码个人 FreeCAD 路径 | 其他机器误杀/找不到进程 | 改为 `-FreeCadPath` / `FREECAD_GUI` 参数 |
| 一键启动依赖 Windows 计划任务 | 企业策略可能禁止 | 保留一键路径，同时提供完整手动启动文档和排障 |
| `frontend/dist` 是生成物 | 仓库包含构建产物 | 为保证无 Node 的干净克隆可直接启动，明确保留并说明重建方式 |
| 旧文档存在“100% 检出/工业级/35 tests”等过度表述 | 误导 | 公开 README 与能力矩阵已重写，旧个人文档不进入公开树 |
| 旧个人文档/截图含本机路径 | 隐私泄露 | 从公开树排除；截图中含路径的图不采用 |

## 7. 发布前阻断问题

| 阻断项 | 当时状态 | 解决/验收条件 |
|---|---|---|
| 目标 GitHub 仓库不存在（HTTP 404） | **阻塞** | 创建公开仓库 `linye-Del/ai-cad-copilot` |
| 无 Git remote / 无 GitHub 认证 | **阻塞** | 完成 GitHub 登录，配置 `origin` |
| 代码/文档未提交 | 已在本地修复，待提交 | 提交并推送 `main` |
| 公开后 README/许可证/截图链接 | 待验证 | 推送后逐项打开检查 |
| 干净目录克隆复现 | 待执行 | 在独立目录 clone 后安装/启动/测试 |
| 敏感信息扫描 | 当前 `.env` 未跟踪，历史未发现真实 Key | 提交后再次扫描 Git 树与历史 |
| 许可证合规 | PyMuPDF 已改为可选；freecad-mcp MIT notice 保留 | 最终报告记录，不把 AGPL 组件默认分发 |
| 新 GUI 验收 | 本次环境不可用 | 如实记录为限制；不能写成“已复验” |

## 8. 发布建议

1. 使用审计后的 E 盘快照创建公开 `main`，旧 `master` 历史保留在本地，不推送个人历史。
2. 先在 GitHub 创建**空**公开仓库，不使用自动 README/License 初始化，避免首次推送冲突。
3. 只推送 `main` 和 `v0.2.0` 标签；不推送旧的本地 `v1.0.0` 标签。
4. 推送后创建 `v0.2.0` Release，正文注明 preview 与 GUI 复验限制。
5. 用干净目录 clone，按 `docs/installation.md` 复现；记录结果到最终报告。
6. 若认证失败，明确告知用户需要完成的最小手动步骤，不索取密码/令牌。
