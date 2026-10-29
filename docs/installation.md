# 安装指南

本文覆盖从零安装 AI CAD Copilot v0.2.0 的完整流程。快速体验可先看
[user_quick_start.md](user_quick_start.md)；出问题看 [troubleshooting.md](troubleshooting.md)。

## 1. 支持矩阵

| 组件 | 支持范围 | 本发布验证 |
|---|---|---|
| 操作系统 | Windows 10 / 11 x64 | Windows 11 |
| FreeCAD | 1.1.x | 1.1.3 |
| Python | 3.10 / 3.11 / 3.12 | 3.12.7 |
| Node.js | 18+（仅重建前端） | 24.19 |
| 浏览器 | 当前版 Edge / Chrome / Firefox | Edge / Chrome |
| 端口 | 默认 8000 | 127.0.0.1:8000 |

> FreeCAD 1.0.x、macOS、Linux 未在本次发布中验证。Backend 本身是跨平台的，但
> `start_ai_cad.ps1` 一键启动只支持 Windows。

## 2. 安装 FreeCAD 1.1.x

从 FreeCAD 官方发布页安装 64 位 Windows 版本：

<https://github.com/FreeCAD/FreeCAD/releases>

安装后确认以下文件存在（路径以实际安装为准）：

```text
C:\Program Files\FreeCAD 1.1\bin\FreeCAD.exe
C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe
```

可用命令行验证：

```powershell
& "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe" --version
```

便携版没有固定安装路径，请在下一步用 `.env` 显式指定 `FREECAD_GUI` 和 `FREECAD_BIN`。

## 3. 获取项目

```powershell
git clone https://github.com/linye-Del/ai-cad-copilot.git
cd ai-cad-copilot
```

如果没有 Git，也可以在 GitHub 页面选择 **Code → Download ZIP**，解压后进入目录。
不要使用旧 D 盘副本覆盖当前项目。

## 4. 创建 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

若 PowerShell 报“禁止运行脚本”，可以：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

或者不激活，直接用虚拟环境解释器：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## 5. 配置 `.env`

```powershell
Copy-Item .env.example .env
```

最小配置可以为空；Live Agent 不需要 DeepSeek Key。

```dotenv
# 可选：Legacy LLM 解析 / LLM 深度审查
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 可选：不填则自动探测
FREECAD_BIN=
FREECAD_GUI=
```

指定便携版 FreeCAD：

```dotenv
FREECAD_BIN=D:\FreeCAD\bin\FreeCADCmd.exe
FREECAD_GUI=D:\FreeCAD\bin\FreeCAD.exe
```

**不要把 `.env` 提交到 Git。** 仓库的 `.gitignore` 已排除它。

## 6. 环境自检

```powershell
python check_environment.py
python check_environment.py --json
```

它会检查 Python、FreeCAD GUI、Python 依赖、8000 端口、Add-on 源目录和目标目录。
失败项会打印具体修复命令。

## 7. 安装 FreeCAD Add-on

推荐用安装脚本：

```powershell
python scripts\install_freecad_addon.py --json
```

默认目标：

```text
%APPDATA%\FreeCAD\Mod\AICADCopilot
```

脚本会：

- 只复制需要的源文件；
- 跳过 `__pycache__`、`.pyc`；
- 写入 `.aicad_install.json` 清单；
- 内容未变化时返回 `unchanged`；
- 校验 `Init.py` / `InitGui.py` / `Workbench.py`。

隔离安装（不碰真实用户配置）：

```powershell
python scripts\install_freecad_addon.py --appdata "D:\temp\aicad-appdata" --json
```

手动安装也可以：把 `freecad_addon\AICADCopilot` 整个目录复制到
`%APPDATA%\FreeCAD\Mod\AICADCopilot`，确保 `Init.py` 就在该目录下，不要多套一层。

## 8. 前端资源

仓库已经包含构建好的 `frontend/dist`，普通用户不需要 Node.js。

只有修改了 `frontend/src` 才需要重建：

```powershell
cd frontend
npm ci
npm run build
cd ..
```

构建输出会覆盖 `frontend/dist`，FastAPI 启动时自动托管。若删除 `dist`，网页会 404；
此时要么恢复 `dist`，要么执行上面的构建命令。

## 9. 启动

### 9.1 一键启动

```text
start_ai_cad.bat
```

### 9.2 手动启动

终端 A：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

终端 B / 桌面：启动 FreeCAD，选择 **AI CAD Copilot** Workbench。

浏览器：<http://127.0.0.1:8000>

### 9.3 验证

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/freecad/status
```

期望：

```json
{
  "ok": true,
  "service": "ai-cad-copilot",
  "execution_mode": "live_gui",
  "freecad_connected": true
}
```

`/api/freecad/status` 中：

```json
{
  "freecad_online": true,
  "active_workbench": "AICADCopilotWorkbench",
  "dock_visible": true,
  "model_tree_visible": true
}
```

## 10. 可选：PDF 工程图审查

`inspection/reviewer.py` 的 PDF 解析使用 PyMuPDF。PyMuPDF 是 **AGPL-3.0 或商业双许可**，
因此没有放进默认 `requirements.txt`。如果你接受其许可证：

```powershell
python -m pip install -r requirements-pdf.txt
```

不安装不影响 Live 建模、TechDraw PDF 导出和 SVG/DXF 审查；只影响对 PDF 图纸做文本/图形解析。

## 11. 代理与镜像（可选）

如果 `pip` 或 `npm` 需要代理，请使用你自己的代理配置，不要把代理凭据写入仓库：

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"
$env:HTTP_PROXY = "http://127.0.0.1:7890"
```

pip 镜像示例：

```powershell
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 12. 卸载

1. 运行 `stop_ai_cad.bat` 停止 Backend 和 FreeCAD。
2. 删除 `%APPDATA%\FreeCAD\Mod\AICADCopilot`。
3. 如启动器创建过计划任务，可在“任务计划程序”中删除 `\AI CAD Copilot\Backend`。
4. 删除项目目录和虚拟环境 `.venv`。

项目不会写入系统级目录，也不会安装 Windows 服务。
