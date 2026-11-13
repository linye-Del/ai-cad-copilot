# GitHub 发布报告

发布日期：2026-11-13（Asia/Shanghai）  
正式项目：`E:\ai cad\a-cad-copilot`  
目标仓库：<https://github.com/linye-Del/ai-cad-copilot>  
发布分支：`main`  
发布版本：`v0.2.0`（GitHub **Pre-release**）  
发布代码 commit：`10cfcfce4ac74dde94df7eea4f72babece40b042`  
Release：<https://github.com/linye-Del/ai-cad-copilot/releases/tag/v0.2.0>

## 结论

**GITHUB RELEASE = PASS**

远程仓库已实际存在、公开可访问，`main` 已推送，MIT 许可证、README、安装/排障/架构文档、
截图和源码均已上传；52 个 Python 测试在本地和从 GitHub 重新克隆的目录中通过；
GitHub Actions CI 在 Python 3.10/3.11/3.12 上全部通过。

本报告必须同时说明一个边界：**Live FreeCAD GUI 链路是 2026-08 的历史验收证据，本次发布
没有在第二台干净 Windows 机器上重新完成一次 GUI 验收**。因此本项目是 `v0.2.0` public
preview，而不是稳定版或工业级产品。

## 1. 仓库信息

| 项目 | 值 |
|---|---|
| 仓库 | <https://github.com/linye-Del/ai-cad-copilot> |
| 所有者 | `linye-Del` |
| 可见性 | Public |
| 默认分支 | `main` |
| 发布分支 | `main` |
| 发布 tag | `v0.2.0` |
| tag 指向 commit | `10cfcfce4ac74dde94df7eea4f72babece40b042` |
| GitHub Release | <https://github.com/linye-Del/ai-cad-copilot/releases/tag/v0.2.0> |
| Release 状态 | Pre-release（`isPrerelease=true`） |
| License | MIT（GitHub 识别为 `MIT License`） |
| GitHub CLI 认证账号 | `linye-Del` |

旧本地 `master` 历史与旧 `v1.0.0` tag 保留在本地，**没有推送**；公开仓库从经过审计的
快照开始，避免把个人简历/面试文档、旧路径和探索性调试材料带入公开历史。

## 2. 发布文件统计（tag `v0.2.0`）

| 指标 | 值 |
|---|---:|
| Git 跟踪文件 | **163** |
| 跟踪文件总字节 | **2,086,999 bytes** |
| 约合 | **1.99 MiB** |
| Python 文件 | 101 |
| 测试文件 | 12 |
| 文档文件（`docs/`） | 16 |
| 截图 | 5 |
| 前端构建产物 | 3（`index.html` + JS + CSS） |
| 最大文件 | `docs/screenshots/live/14_freecad_techdraw_delivery_clean.png`（305,833 bytes） |
| 默认分支 commit | `10cfcfc`（报告本身在 tag 之后作为文档提交追加到 `main`） |

根目录包含：README、LICENSE、CHANGELOG、CONTRIBUTING、SECURITY、THIRD_PARTY_NOTICES、
requirements、启动/停止脚本、Backend/Agent/CAD/Inspection/Knowledge/Frontend/Add-on/
Tests/Examples/Docs。

## 3. 敏感信息检查

| 检查 | 结果 |
|---|---|
| 工作区 `.env` | 存在于 E 盘本地，**未提交**；`.gitignore` 排除 |
| tag 中是否有 `.env` | 无；只有 `.env.example` 模板 |
| 高熵 Key 模式（`sk-*`、`ghp_*`、`github_pat_*`、`AKIA*`、私钥） | tag 树与历史扫描均 **无匹配** |
| GitHub token | 仅用于本次认证，未写入仓库、README、报告或提交 |
| 个人路径/用户名 | 公开树中的 `docs`、README、脚本已清理；含路径的旧截图/文档不发布 |
| 日志/PID/缓存/虚拟环境 | `.gitignore` 排除，未提交 |
| 截图内容 | 只保留 5 张不含个人路径的真实 GUI/网页截图 |

扫描命令（结果：无匹配）：

```powershell
git grep -n -E "sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY" v0.2.0 -- .
git ls-tree -r --name-only v0.2.0 | Where-Object { $_ -eq ".env" }
```

## 4. 许可证检查

| 项目 | 结果 |
|---|---|
| 主许可证 | MIT，文件存在，GitHub 识别 |
| 第三方适配代码 | `neka-nat/freecad-mcp` MIT；版权与 MIT 全文保留在 `THIRD_PARTY_NOTICES.md` |
| FreeCAD | 独立 LGPL-2.1+ 运行时依赖，不随仓库分发二进制 |
| Python 依赖 | 在 `THIRD_PARTY_NOTICES.md` 列出许可证与上游链接 |
| PyMuPDF | AGPL-3.0/商业双许可，**已从默认 requirements 移除**，只在 `requirements-pdf.txt` 显式 opt-in |
| 不能公开分发的文件 | 未发现；个人简历/面试/交接文档从公开树排除 |

许可证兼容性仍建议在商业分发前由专业人士复核；本报告不是法律意见。

## 5. README 与文档检查

| 检查 | 结果 |
|---|---|
| 根 README | 中英双语，含 20 个要求章节、能力矩阵、架构、截图、安装、启动、示例、测试、限制、路线图、许可证、贡献、联系 |
| README 图片 | 5 张相对路径图片，raw.githubusercontent.com 返回 200 |
| 安装文档 | `docs/installation.md`，覆盖 Windows/FreeCAD/Python/Node、插件位置、手动/一键、代理、卸载 |
| 快速启动 | `docs/user_quick_start.md`，含 Bridge 验证、阶梯轴、工程图、停止 |
| 故障排查 | `docs/troubleshooting.md`，含 Backend、端口、Bridge、Workbench、计划任务、dist、PDF 依赖 |
| 架构 | `docs/architecture.md` + `docs/assets/architecture_v2.svg`，区分 Live 与 Legacy |
| 开发/API/安全/第三方 | `docs/development.md`、`docs/api.md`、`SECURITY.md`、`THIRD_PARTY_NOTICES.md` |
| 审计 | `docs/github_release_audit.md` |
| 相对链接 | README 与 docs 链接已检查；唯一发布前缺失是本报文，现已补齐 |
| GitHub 页面 | 仓库主页 HTTP 200，README、LICENSE、截图 raw 均 200 |

## 6. 测试与复现结果

| 检查 | 结果 |
|---|---|
| 本地 E 盘测试 | **52 passed**（Windows 11，Python 3.12.7，32.89s） |
| 从 GitHub 重新克隆 | `git clone https://github.com/linye-Del/ai-cad-copilot.git` 成功 |
| 克隆目录测试 | **52 passed**（29.63s，未使用 E 盘 `.env`） |
| 克隆目录 Backend | 启动成功；`/api/health`、`/`、`/api/part-types`、`/api/freecad/status` 均 200 |
| 前端生产构建 | Vite 构建成功；`frontend/dist` 为 3 个文件 |
| Legacy FreeCADCmd 建模 | 测试通过（bolt 生成 FCStd/STEP/STL） |
| GitHub Actions CI | **success**：Python 3.10/3.11/3.12 + py_compile，4 个 job 全通过 |
| CI 地址 | <https://github.com/linye-Del/ai-cad-copilot/actions/runs/43370197663> |
| FreeCAD GUI 复验 | **未完成**；本次自动化会话中 GUI 进程提前退出，使用 2026-08 历史验收记录 |

克隆复现命令：

```powershell
git clone https://github.com/linye-Del/ai-cad-copilot.git
cd ai-cad-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests -q
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

## 7. 真正可用的功能

- FastAPI Backend：健康检查、Live Bridge 状态、Legacy 会话/建模/审查、静态前端。
- Vue 3 前端：生产构建成功，FastAPI 直接托管。
- Live FreeCAD Agent：自然语言 → PartSpec → Design Engine → CadPlan → 本机 WebSocket →
  FreeCAD Add-on（历史 GUI 证据）。
- 原生参数化特征：Body / Sketch / Pad / Pocket / AdditiveHelix / Chamfer / Fillet
  （历史 GUI 证据）。
- 阶梯轴与 M10 螺栓的 Live 建模、Undo/Redo、FCStd 重开（历史 GUI 证据）。
- 同 Document TechDraw：页面、视图、关联尺寸、标题栏、PDF；DrawingLayoutEngine 与
  DrawingValidator 有单元测试和历史出图证据。
- 27 条机械设计规则、STEP 特征/可制造性检查、公差检查、可选 LLM 审查。
- Windows 一键启动/停止脚本；手动两终端启动流程。
- 法兰、带孔板的 PartSpec/CadPlan 与单元测试（Live GUI 尚未在本版本复验）。

## 8. 尚未完成 / 不应宣称

- 任意拓扑自动规划；复杂零件族；精确渐开线齿轮（仅 Legacy 简化齿形）。
- 装配体、干涉检查、FEA/CalculiX、图纸 OCR/图像输入。
- 完整 GD&T、表面粗糙度、焊接符号、BOM、剖视/局部放大自动生成。
- 第二台干净 Windows 机器的 FreeCAD GUI 复验；工业级自动出图认证。
- macOS/Linux 一键启动；当前一键脚本仅 Windows。
- PyMuPDF 默认安装（AGPL，需 opt-in）。

## 9. 已知问题

| 问题 | 影响 | 状态 |
|---|---|---|
| 本次未重新拉起 FreeCAD GUI | 只能引用历史 GUI 证据 | 已在 README/Release/报告明确标注 |
| 一键启动依赖 Windows 计划任务 | 企业策略可能禁用 | 保留一键路径，文档给出手动两终端方案 |
| `frontend/dist` 是生成物 | 仓库含构建产物 | 为保证无 Node 的干净克隆可启动，明确保留并给重建命令 |
| PyMuPDF AGPL | 默认依赖会有许可证义务 | 移除默认安装，改为 `requirements-pdf.txt` |
| DXF 导出不稳定 | 某些 FreeCAD 版本可能崩溃 | 主路径使用 TechDraw PDF/SVG；不默认依赖 DXF |
| 法兰/带孔板 Live GUI 未复验 | 不能宣称完整 GUI 通过 | 标记“部分验证”；不写成已验证 |
| 个人职业文档未公开 | 公开树比 E 盘本地少这些文件 | 隐私取舍；公开树为策展版本 |

## 10. 下一步建议

1. 在一台干净的 Windows 机器上按 `docs/installation.md` 做一次完整 GUI 验收，记录 FreeCAD
   版本、Bridge 状态、特征树、TechDraw PDF 与截图。
2. 增加 `v0.2.x` GUI 回归矩阵，覆盖阶梯轴、M10 螺栓、法兰、带孔板和 Undo/Redo/重开。
3. 将法兰/带孔板从“部分验证”提升为“已验证”，或明确标注为实验性。
4. 完成 GD&T、粗糙度、中心线、剖视/局部放大与 BOM 的制图规则。
5. 评估替代 AGPL PDF 库，或把 PDF 审查拆成可选服务。
6. 增加装配、FEA、图像输入与 Windows 安装器/便携包。

## 11. 对最终六个问题的回答

1. **仓库链接**：<https://github.com/linye-Del/ai-cad-copilot>
2. **如何下载**：
   ```powershell
   git clone https://github.com/linye-Del/ai-cad-copilot.git
   ```
   或 GitHub 页面 **Code → Download ZIP**。
3. **如何运行**：安装 Python 3.10–3.12、FreeCAD 1.1.x；`pip install -r requirements.txt`；
   `python scripts\install_freecad_addon.py`；双击 `start_ai_cad.bat`，或按
   `docs/user_quick_start.md` 手动启动 Backend + FreeCAD。
4. **真正可用的功能**：见第 7 节；核心是 Live 阶梯轴/M10 螺栓（历史 GUI 证据）、原生特征树、
   同 Document TechDraw、规则/STEP/公差检查、FastAPI + Vue 前端、Windows 一键启动。
5. **尚未完成**：任意拓扑、精确齿轮、装配/FEA/OCR、完整 GD&T/BOM、第二台干净 GUI 复验、
   非 Windows 一键启动。
6. **是否已成功推送**：**是**。远程 `main` 与 tag `v0.2.0` 已存在，仓库公开，CI 通过。

## 12. 发布门禁核对

- [x] GitHub 远程仓库实际存在
- [x] 仓库为 Public
- [x] `main` 已推送，远程与本地 commit 一致
- [x] `v0.2.0` tag 已推送，Release 为 Pre-release
- [x] MIT 许可证存在且被 GitHub 识别
- [x] README 中文/英文、图片、相对链接可用
- [x] 安装/快速启动/排障/架构/API/开发/安全文档存在
- [x] 敏感信息扫描无真实 Key / 无私钥 / 无 `.env`
- [x] 52 个测试通过
- [x] 从 GitHub 重新克隆后 52 个测试通过
- [x] CI 全部通过
- [x] 克隆目录 Backend/网页冒烟通过
- [x] Live GUI 复验未完成已如实标注（不伪装为通过）

**最终状态：GITHUB RELEASE = PASS（v0.2.0 public preview；GUI 为历史验收，未在本版本第二台干净机器复验）。**
