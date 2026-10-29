# 故障排查

按“先确认入口，再看端口，再看 Bridge，最后看 FreeCAD 插件”的顺序排查。
不要用任务管理器批量结束 Python 进程，也不要把 API Key、令牌或完整个人路径贴到 Issue。

## 0. 先收集最小信息

```powershell
python --version
& "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe" --version
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/freecad/status
```

日志：

```text
logs\launcher.log
logs\backend.log
logs\backend.lifecycle.json
logs\backend.pid
logs\freecad.log
output\logs\app.log
```

在 Issue 中请只保留相关片段，删除用户名、绝对路径、Key 和代理凭据。

## 1. Backend 未运行

**现象**：`http://127.0.0.1:8000` 打不开，或 `Invoke-RestMethod` 报“无法连接到远程服务器”。

**检查**

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
Get-Content .\logs\backend.log -Tail 80
```

**手动启动**

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

如果手动能启动，说明依赖和代码没问题，问题在启动器/计划任务；如果手动也失败，先修 Python 依赖。

**常见原因**

- 没有激活虚拟环境，使用了另一个 Python；
- 依赖未安装完整：`python -m pip install -r requirements.txt`；
- 工作目录不是项目根目录，导致 `config/` 或 `frontend/dist` 找不到；
- `output\logs` 不可写（权限/杀毒软件）；
- 8000 端口被占用。

## 2. 8000 端口被占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process -Id <PID> | Select-Object Id,ProcessName,Path
```

如果占用者不是 `python.exe`（或不是本项目的 `backend_host.py`），关闭对应程序或换端口：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

换端口后必须同步修改启动器或 `AICAD_BACKEND_WS`，否则 FreeCAD Add-on 仍会连接 8000。
不要 `Stop-Process` 你不认识的 PID。

## 3. 网页能开，但 FreeCAD 没有连接

**检查状态**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/freecad/status
```

若 `freecad_online=false`：

1. 确认 FreeCAD 是 **1.1.x**，且真正打开了 GUI（不是只剩 `FreeCADCmd`）；
2. 关闭所有 FreeCAD 窗口，再启动一次（插件只在启动时加载）；
3. 确认插件目录：

   ```text
   %APPDATA%\FreeCAD\Mod\AICADCopilot\Init.py
   %APPDATA%\FreeCAD\Mod\AICADCopilot\InitGui.py
   %APPDATA%\FreeCAD\Mod\AICADCopilot\Workbench.py
   ```

4. 确认没有多套一层目录，例如
   `...\Mod\AICADCopilot\AICADCopilot\Init.py` 是错误结构；
5. 在 FreeCAD 中手动切换到 **AI CAD Copilot** Workbench；
6. 看 `logs\freecad.log` 是否有 `AI CAD Copilot failed to start`、`ImportError`、
   `No module named AICADCopilot`；
7. 确认 Backend 监听的是 `127.0.0.1`，Add-on 拒绝非本机地址。

**重装插件**

```powershell
python scripts\install_freecad_addon.py --json
```

然后完全退出 FreeCAD 再启动。

## 4. Workbench 菜单里没有 AI CAD Copilot

- FreeCAD 版本过低或使用了不同的用户配置目录；
- 插件安装到了错误的 `%APPDATA%`（例如以管理员身份运行 FreeCAD）；
- FreeCAD 启动时插件报错，Workbench 注册失败。

查看 `logs\freecad.log` 和 FreeCAD 的 Report View。确认当前用户的 APPDATA：

```powershell
$env:APPDATA
Test-Path "$env:APPDATA\FreeCAD\Mod\AICADCopilot\InitGui.py"
```

如果使用了便携版或隔离配置，必须让 FreeCAD 使用同一个用户目录。

## 5. 一键启动失败：计划任务

启动器会在当前用户下创建 `\AI CAD Copilot\Backend` 计划任务，用于让 Backend 在启动器退出后
继续运行。不需要管理员权限，但某些学校/公司策略会禁用任务计划。

**查看**

```powershell
Get-ScheduledTask -TaskPath "\AI CAD Copilot\*" -ErrorAction SilentlyContinue |
  Select-Object TaskName,State
```

**处理**

- 如果任务不存在或被禁用，优先使用 [user_quick_start.md](user_quick_start.md) 的手动启动；
- 手动启动的 Backend 同样可以被 `stop_ai_cad.ps1` 识别（通过 pid/health/listener 校验）；
- 不要在任务计划程序中把任务改成“无论用户是否登录都运行”，这会改变桌面交互和权限模型；
- 不要强制结束未知 Python 进程。

启动失败时 `logs\launcher.log` 会记录 Task State、Last Result、8000 状态、PID 文件和
health 结果。把这些片段（去掉用户名/路径）附到 Issue。

## 6. 网站 404 或空白

**404**：`frontend/dist/index.html` 不存在。仓库应自带 `frontend/dist`；如果你删除了它：

```powershell
cd frontend
npm ci
npm run build
cd ..
```

然后重启 Backend。

**空白页**：打开浏览器开发者工具，看 Console 和 Network：

- `/assets/*.js` 是否 404；
- 是否被代理/缓存拦截；
- 是否访问了旧缓存，强制刷新（Ctrl+F5）。

## 7. Python 依赖 / DLL 冲突

**Anaconda 与 FreeCAD 的 Qt/Python DLL 冲突**是常见问题。项目已经通过子进程环境净化和
虚拟环境隔离降低风险，但请：

- Backend 使用项目 `.venv`，不要使用系统 Anaconda；
- 不要把 Anaconda 的 `Library\bin` 放到 FreeCAD 的 PATH 前面；
- 不要设置会污染子进程的 `PYTHONPATH` / `PYTHONHOME`。

检查：

```powershell
where.exe python
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

如果 `python` 指向 Anaconda，重新激活 `.venv` 或用绝对路径运行。

## 8. FreeCAD GUI 启动后立即退出

先在终端直接运行，保留输出：

```powershell
& "C:\Program Files\FreeCAD 1.1\bin\FreeCAD.exe" --log-file .\logs\freecad-manual.log
```

检查：

- 显卡驱动 / 远程桌面 / 无显示器会话是否支持 Qt；
- `logs\freecad-manual.log` 最后的模块加载错误；
- 是否同时启动了多个 FreeCAD 实例；
- 是否有残留的 `FreeCAD_*.lock` 恢复文件。

启动器会隔离明显陈旧的恢复锁，但不会删除你正在使用的文档。不要手动删除不确定的
`FreeCAD_Doc_*` 目录。

## 9. PDF 审查报缺少 pymupdf

这是**预期行为**。PyMuPDF 是 AGPL-3.0/商业双许可，默认不安装。若你接受其许可证：

```powershell
python -m pip install -r requirements-pdf.txt
```

不安装不影响 Live 建模、TechDraw PDF 导出、SVG/DXF 审查。

## 10. DXF 导出失败 / FreeCAD 崩溃

FreeCAD 1.1.3 的 `importDXF.export` 存在概率性崩溃，项目默认不把 DXF 作为主路径。
请使用 TechDraw PDF 或 SVG。若必须 DXF，建议在独立 FreeCAD 进程中导出，并保留 FCStd。

## 11. 阶梯轴尺寸看起来“不对”

Live Agent 在没有扭矩、轴承、联轴器接口时，会用概念设计比例 `d≈L/10` 生成三段轴，
并在 `assumptions` 中明确标记。它不是强度校核结果。

要得到设计引擎按扭矩计算的轴径，需要提供扭矩（例如通过 API 的 `torque_nm`，或在支持该字段的
入口传入）。生产设计前必须用真实载荷、材料和标准复核。

## 12. 停止后端口仍被占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

先确认 PID 的命令行属于本项目：

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" |
  Select-Object ProcessId,Name,CommandLine
```

如果确认是本项目的 `backend_host.py`，再按 `stop_ai_cad.ps1` 的日志处理；不要直接强杀未知进程。
