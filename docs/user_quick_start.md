# AI CAD Copilot 快速启动

本文面向第一次运行项目的用户。目标是在 5–10 分钟内看到：

1. 浏览器打开 `http://127.0.0.1:8000`；
2. FreeCAD 右侧出现 **AI CAD Copilot** 面板；
3. 输入“创建一个300mm阶梯轴”后，FreeCAD 中出现真实的参数化特征树；
4. 输入“为当前模型生成工程图”后，得到同一 Document 的 TechDraw PDF。

> 这是 v0.2.0 预览版。真正的 GUI 验收记录见
> [live_freecad_test.md](live_freecad_test.md)；如果你在另一台机器上运行，请按本文逐步确认
> `FreeCAD Connected`，不要只看启动脚本退出码。

## 1. 准备环境

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 / 11 x64 |
| FreeCAD | 1.1.x（实测 1.1.3） |
| Python | 3.10–3.12（实测 3.12.7） |
| Node.js | 18+，仅在你修改前端时需要 |
| 端口 | `127.0.0.1:8000` 未被占用 |

FreeCAD 的默认安装位置通常类似：

```text
C:\Program Files\FreeCAD 1.1\bin\FreeCAD.exe
C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe
```

便携版也可以，只要在 `.env` 中写 `FREECAD_GUI` / `FREECAD_BIN` 的绝对路径。

## 2. 安装 Python 依赖

在项目根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 PowerShell 禁止激活脚本，可直接使用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. 配置（可选）

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
# 可选；不填也能使用 Live Agent 和规则回退
DEEPSEEK_API_KEY=

# 可选；留空时自动探测
FREECAD_BIN=
FREECAD_GUI=
```

`FREECAD_BIN` 指向 `FreeCADCmd.exe`（Legacy 无头建模），`FREECAD_GUI` 指向
`FreeCAD.exe`（Live 模式）。

## 4. 安装 FreeCAD 插件

```powershell
python scripts\install_freecad_addon.py --json
```

默认安装到：

```text
%APPDATA%\FreeCAD\Mod\AICADCopilot
```

安装脚本会校验 `Init.py`、`InitGui.py`、`Workbench.py` 是否存在，并写入安装清单。
便携版或隔离测试可加：

```powershell
python scripts\install_freecad_addon.py --appdata "D:\temp\aicad-appdata" --json
```

## 5. 启动方式 A：一键启动（推荐）

双击项目根目录的：

```text
start_ai_cad.bat
```

启动器会依次检查：

- Python 版本与依赖；
- FreeCAD GUI 路径；
- 8000 端口；
- Workbench 安装/更新；
- Backend 健康检查与网站首页；
- FreeCAD Workbench、Dock、模型树和 Bridge 连接。

看到类似输出即表示成功：

```text
  FreeCAD OK
  AI Bridge Connected
  FreeCAD Connected: True
  Workbench: AICADCopilotWorkbench
  Dock Panel: True
```

启动器使用当前用户级 Windows 计划任务托管 Backend，不需要管理员权限。停止时双击
`stop_ai_cad.bat`，或运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop_ai_cad.ps1
```

## 6. 启动方式 B：手动启动（计划任务被禁用时）

如果公司/学校策略禁止创建计划任务，使用两个终端。

**终端 A：Backend**

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

**终端 B 或桌面：FreeCAD**

正常启动 FreeCAD，选择 **AI CAD Copilot** Workbench。若 Workbench 未出现，先关闭 FreeCAD，
确认插件已安装到 `%APPDATA%\FreeCAD\Mod\AICADCopilot`，再重新启动。

**浏览器**

打开 <http://127.0.0.1:8000>。

## 7. 确认 Bridge 真的连上了

不要只看网页是否能打开。检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/freecad/status
```

关键字段：

```json
{
  "freecad_online": true,
  "active_workbench": "AICADCopilotWorkbench",
  "dock_visible": true,
  "model_tree_visible": true
}
```

`/api/health` 里应看到：

```json
{
  "ok": true,
  "service": "ai-cad-copilot",
  "execution_mode": "live_gui",
  "freecad_connected": true
}
```

如果 `freecad_online` 为 `false`，按 [troubleshooting.md](troubleshooting.md) 的顺序排查。

## 8. 创建第一个阶梯轴

在网页 **Live FreeCAD Agent** 输入框，或 FreeCAD 右侧 Dock 中输入：

```text
创建一个300mm阶梯轴
```

预期结果：

- 当前 FreeCAD Document 中出现 `Body`、`Origin`、3 个 `Sketch`、3 个 `Pad`；
- 出现 `Chamfer`、`Fillet`；
- `Sketch` 报告 fully constrained；
- 右侧 Dock 显示 `FreeCAD Connected`，进度走到 `save_document`；
- 模型可 Undo / Redo，保存为 `.FCStd` 后重新打开，特征树仍在。

> 没有提供扭矩、轴承或联轴器接口时，Design Engine 会按概念设计比例给出轴径，并在结果中
> 标记为 `assumption`。这不是强度校核结果，生产设计前必须用真实载荷复核。

## 9. 生成工程图

保持模型为活动 Document，输入：

```text
为当前模型生成工程图
```

系统会：

1. 从当前 Document 创建 TechDraw 页面；
2. 选择比例、布置主视图/端视图/轴测视图；
3. 创建关联尺寸、中心线和标题栏；
4. 运行 `DrawingLayoutEngine` 与 `DrawingValidator`；
5. 通过后导出 PDF。

产物默认在：

```text
output\live\drawing_<id>\<DocumentName>_drawing.pdf
```

返回结果中的 `drawing_layout_validated` 应为 `PASS`。如果失败，先看结果 JSON 中的
`layout_validation` 字段，再查 [troubleshooting.md](troubleshooting.md)。

## 10. 正常停止

推荐：

```text
stop_ai_cad.bat
```

它会请求 FreeCAD 正常关闭（有未保存模型时按提示保存），并让 Backend 安全退出。
不要直接结束 Python 进程；否则 `logs\backend.pid` 可能残留。若确实需要手动清理，先确认
8000 端口上的进程属于本项目，再按 [troubleshooting.md](troubleshooting.md) 的步骤处理。
