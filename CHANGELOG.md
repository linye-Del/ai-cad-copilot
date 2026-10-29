# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
and versioning follows [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.2.0] - 2026-10-29

First curated public release. This version number intentionally supersedes the local-only
`v1.0.0` tag, which represented an earlier prototype and is not published as a stable release.

### Added

- Live FreeCAD Agent: typed `PartSpec` → Design Engine → allow-listed `CadPlan` → localhost
  WebSocket → FreeCAD Add-on → native PartDesign features.
- Same-document TechDraw generation with `DrawingLayoutEngine`, `DrawingValidator`, and
  `MechanicalDrawingRuleEngine`.
- Native stepped-shaft, M-series bolt, flange, and hole-plate plans; `AdditiveHelix` thread,
  Pocket, Chamfer, and Fillet operations.
- FastAPI gateway/status/event endpoints and a Vue 3 Live Agent panel.
- Bilingual README, installation, quick start, troubleshooting, architecture, API, security,
  and third-party notices.
- Release audit/report documents and curated screenshots.

### Changed

- Public release is a curated branch; personal career/handover notes and exploratory debug
  material are excluded from the public tree.
- The frontend production bundle (`frontend/dist`) is included so a clean clone can be served
  without Node.js.
- PyMuPDF moved out of default dependencies because it is AGPL-3.0/commercial; PDF review is
  now an explicit opt-in via `requirements-pdf.txt`.

### Fixed

- `manufacturability_checker.check()` no longer raises `NameError` when features are supplied.
- Portability: MCP/cross-process test scripts no longer hard-code a local `E:\` path.
- PDF review returns a clear `missing_optional_dependency` error instead of crashing.
- Cold-start validation accepts an explicit FreeCAD path instead of a personal install path.

### Verification

- Python: 52 passed on Windows + Python 3.12.7.
- Frontend: Vite production build passed.
- Legacy FreeCADCmd modelling smoke passed.
- Live GUI acceptance: historical evidence from Aug 2026; not re-run on a second clean machine
  for this release.

## [1.0.0] - 2026-08-20

AI CAD Copilot First Release —— 自然语言驱动的 FreeCAD 机械设计智能体。

### Features

- **LLM CAD Agent**：LangChain ReAct Agent 通过 MCP 协议驱动建模，支持多轮对话式完成机械设计
- **FreeCAD MCP integration**：FastMCP 协议桥接（create_session / create_part / make_drawing / validate_part），
  会话磁盘持久化 + 子进程崩溃自愈
- **Automatic CAD generation**：中文自然语言 → 结构化参数 → FreeCAD 无头参数化建模
  （六角头螺栓 / 阶梯轴 / 法兰盘 / 直齿圆柱齿轮，GB/T 标准派生）
- **Engineering drawing generation**：程序化 SVG 三视图（国标第一角投影）+ 尺寸标注 + 标题栏
- **AI drawing inspection**：机械设计决策系统（27 条规则 × 5 类别，四段式工程解释）
  + 工程图公差检查（H7/g6、IT 等级、缺标检测）+ LLM 深度审查（标准条文引用）
- **STEP model analysis**：OpenCascade 三维实体审查（孔/槽/圆角/倒角/壁厚/内角特征提取，
  可制造性/机械设计/装配风险检查）

### Architecture

- FastAPI 后端 + Vue3 前端 + FreeCAD(OpenCascade) 内核三层架构
- config.yaml 三级配置（环境变量 > YAML > 默认值）
- 结构化日志（控制台 + 滚动文件）
- 全局异常处理（统一错误格式）

### Demo

- 3 分钟完整演示流程（一键 Demo：需求 → AI 理解 → 参数推荐 → CAD 生成 → 工程图 → 审查 → 优化报告）
- 工业级案例：500Nm 电机传动轴设计（6 步流程，交付 model.FCStd / drawing.svg / design_report.md）

### Docs

- README（9 章节）：项目介绍 / 应用场景 / 系统架构 / LLM Agent 流程 / MCP 通信 /
  CAD 生成流程 / 图纸审查流程 / Demo 截图 / Future Work
- docs/：architecture.md、api.md、demo.md、development.md
- CONTRIBUTING.md、CHANGELOG.md

### CI

- GitHub Actions：Python 环境 + 单元测试（规则引擎/公差/SVG/API）
