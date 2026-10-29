[CmdletBinding()]
param(
    [string]$FreeCADBin = "",
    [string]$AppDataRoot = $env:AICAD_APPDATA_ROOT,
    [int]$Port = 8000,
    [int]$BackendTimeoutSeconds = 60,
    [int]$FreeCADTimeoutSeconds = 45,
    [switch]$NoBrowser,
    [switch]$NoPause,
    [switch]$NoShortcuts,
    [string]$FreeCADUserConfig = "",
    [string]$FreeCADSystemConfig = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$startedAt = Get-Date
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$logDir = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$launcherLog = Join-Path $logDir "launcher.log"
$logHeader = "[{0}] [INFO] ===== AI CAD Copilot launcher start =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff")
Add-Content -LiteralPath $launcherLog -Value $logHeader -Encoding UTF8
Write-Host "正在启动 AI CAD Copilot，请稍候..." -ForegroundColor Cyan

function Write-LauncherLog([string]$Message, [string]$Level = "INFO") {
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Level, $Message
    Add-Content -LiteralPath $launcherLog -Value $line -Encoding UTF8
}

function Write-Step([string]$Text) {
    Write-Host "`n→ $Text" -ForegroundColor Cyan
    Write-LauncherLog $Text
}

function Stop-WithMessage([string]$Message) {
    Write-LauncherLog $Message "ERROR"
    Write-Host "`n启动失败：$Message" -ForegroundColor Red
    Write-Host "启动日志：$launcherLog" -ForegroundColor Yellow
    if (-not $NoPause) {
        Write-Host "请修复上述问题后重新双击 start_ai_cad.bat。" -ForegroundColor Yellow
    }
    exit 1
}

function Get-LogDiagnostic([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "日志文件不存在：$Path" }
    $important = Get-Content -LiteralPath $Path -Tail 160 -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "Traceback|Error|Exception|ModuleNotFound|ImportError|AICADCopilot|InitGui" } |
        Select-Object -Last 20
    if (-not $important) {
        $important = Get-Content -LiteralPath $Path -Tail 20 -ErrorAction SilentlyContinue
    }
    return (($important | ForEach-Object { $_.Trim() }) -join " | ")
}

function Get-AICadHealth {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($health.ok -eq $true -and $health.service -eq "ai-cad-copilot") { return $health }
    } catch {}
    return $null
}

function Get-ListeningPid {
    $pattern = "^\s*TCP\s+127\.0\.0\.1:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p TCP 2>$null)) {
        if ($line -match $pattern) { return [int]$Matches[1] }
    }
    return $null
}

function Get-BackendPidFileValue {
    $pidFile = Join-Path $logDir "backend.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return 0 }
    $raw = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsed = 0
    if ([int]::TryParse([string]$raw, [ref]$parsed)) { return $parsed }
    return 0
}

function Get-BackendTaskStatus {
    $taskHelper = Join-Path $projectRoot "scripts\backend_task.ps1"
    try {
        $raw = & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
            -File $taskHelper -Mode Status 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $raw) {
            return [pscustomobject]@{ task_exists = $false; task_state = "QueryFailed"; query_error = (($raw | Out-String).Trim()) }
        }
        return ((($raw | Out-String).Trim()) | ConvertFrom-Json)
    } catch {
        return [pscustomobject]@{ task_exists = $false; task_state = "QueryFailed"; query_error = $_.Exception.Message }
    }
}

function Get-BackendFailureReport([string]$Reason) {
    $task = Get-BackendTaskStatus
    $listenerPid = Get-ListeningPid
    $health = Get-AICadHealth
    $pidFileValue = Get-BackendPidFileValue
    $taskExists = if ($task.task_exists) { "存在" } else { "不存在" }
    $taskResult = if ($null -ne $task.last_task_result_hex) {
        "$($task.last_task_result_hex) ($($task.last_task_result))"
    } else { "无法读取" }
    $listenerState = if ($listenerPid) { "LISTENING (PID $listenerPid)" } else { "NOT LISTENING" }
    $healthState = if ($health) { "HTTP 200 (PID $($health.pid))" } else { "failed" }
    $pidState = if ($pidFileValue -gt 0) { [string]$pidFileValue } else { "missing/stale" }
    $backendLog = Join-Path $logDir "backend.log"
    $diagnostic = Get-LogDiagnostic $backendLog
    return @"
Backend 启动失败：$Reason
Scheduled Task: $taskExists，State=$($task.task_state)，Config=$($task.config_version)，Matches=$($task.config_matches)
Task Last Result: $taskResult
Task Principal: $($task.principal_user)，LogonType=$($task.principal_logon_type)，RunLevel=$($task.principal_run_level)
Task Action: $($task.action)
Task WorkingDirectory: $($task.working_directory)
8000: $listenerState
backend.pid: $pidState
Health: $healthState
Log: $backendLog
Recent diagnostic: $diagnostic
"@
}

function Invoke-BackendTaskStart {
    $launchOutput = & $python (Join-Path $projectRoot "scripts\launch_backend.py") `
        --project-root $projectRoot --host 127.0.0.1 --port $Port 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $launchOutput) {
        throw "计划任务注册/启动失败：$(($launchOutput | Out-String).Trim())"
    }
    try {
        return ((($launchOutput | Out-String).Trim()) | ConvertFrom-Json)
    } catch {
        throw "计划任务启动结果无法解析：$($_.Exception.Message)；输出=$(($launchOutput | Out-String).Trim())"
    }
}

function Sync-BackendPidState {
    $pidFile = Join-Path $logDir "backend.pid"
    $filePid = $null
    if (Test-Path -LiteralPath $pidFile) {
        $raw = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $parsedPid = 0
        if ([int]::TryParse([string]$raw, [ref]$parsedPid)) {
            $filePid = $parsedPid
        } else {
            $filePid = $null
        }
    }
    $health = Get-AICadHealth
    $listenerPid = Get-ListeningPid
    if ($health -and $listenerPid -and [int]$health.pid -eq $listenerPid -and
            (Get-Process -Id $listenerPid -ErrorAction SilentlyContinue)) {
        if ($filePid -ne $listenerPid) {
            Set-Content -LiteralPath $pidFile -Value $listenerPid -Encoding ASCII
            Write-LauncherLog "PID文件已修复：原值=$filePid，当前health/listener PID=$listenerPid" "WARNING"
        }
        return $health
    }
    if (Test-Path -LiteralPath $pidFile) {
        $processExists = if ($filePid) { [bool](Get-Process -Id $filePid -ErrorAction SilentlyContinue) } else { $false }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Write-LauncherLog "清理stale backend.pid：PID=$filePid，process_exists=$processExists，listener=$listenerPid，health=$([bool]$health)" "WARNING"
    }
    return $null
}

function Get-WebsiteReady {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
        $contentType = [string]$response.Headers["Content-Type"]
        if ($response.StatusCode -eq 200 -and $contentType -match "text/html" -and
                $response.Content -match "AI CAD Copilot") {
            return $true
        }
    } catch {}
    return $false
}

function Get-FreeCADStatus {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/freecad/status" -TimeoutSec 2
    } catch {
        return $null
    }
}

if ($AppDataRoot) {
    $resolvedAppData = [System.IO.Path]::GetFullPath($AppDataRoot)
    New-Item -ItemType Directory -Path $resolvedAppData -Force | Out-Null
    $env:APPDATA = $resolvedAppData
    if (-not $FreeCADUserConfig) {
        $FreeCADUserConfig = Join-Path $resolvedAppData "FreeCAD\user.cfg"
    }
    if (-not $FreeCADSystemConfig) {
        $FreeCADSystemConfig = Join-Path $resolvedAppData "FreeCAD\system.cfg"
    }
}
if (-not $env:APPDATA) {
    Stop-WithMessage "Windows APPDATA 环境变量不可用。"
}
Write-LauncherLog "项目路径=$projectRoot"
Write-LauncherLog "APPDATA=$env:APPDATA"
Write-LauncherLog "Launcher PID=$PID，Session ID=$([System.Diagnostics.Process]::GetCurrentProcess().SessionId)"
try {
    $launcherParent = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    Write-LauncherLog "Launcher Parent PID=$($launcherParent.ParentProcessId)"
} catch {
    Write-LauncherLog "Launcher Parent PID=无法读取（$($_.Exception.Message)）" "WARNING"
}

function Quarantine-StaleFreeCADRecovery {
    if (Get-Process -Name "FreeCAD" -ErrorAction SilentlyContinue) { return }
    $cacheRoot = Join-Path $env:TEMP "FreeCAD\v1-1\Cache"
    if (-not (Test-Path -LiteralPath $cacheRoot -PathType Container)) { return }
    $staleLocks = @(Get-ChildItem -LiteralPath $cacheRoot -Filter "FreeCAD_*.lock" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -match '^FreeCAD_(\d+)$' -and
            -not (Get-Process -Id ([int]$Matches[1]) -ErrorAction SilentlyContinue) })
    if (-not $staleLocks) { return }
    $quarantine = Join-Path $logDir ("recovery_quarantine\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Path $quarantine -Force | Out-Null
    foreach ($lock in $staleLocks) {
        $null = $lock.BaseName -match '^FreeCAD_(\d+)$'
        $stalePid = [int]$Matches[1]
        $recoveries = @(Get-ChildItem -LiteralPath $cacheRoot -Directory -Filter "FreeCAD_Doc_*_$stalePid" -ErrorAction SilentlyContinue)
        foreach ($item in $recoveries) {
            Move-Item -LiteralPath $item.FullName -Destination (Join-Path $quarantine $item.Name)
            Write-LauncherLog "隔离stale FreeCAD恢复目录=$($item.FullName) -> $quarantine" "WARNING"
        }
        Move-Item -LiteralPath $lock.FullName -Destination (Join-Path $quarantine $lock.Name)
        Write-LauncherLog "隔离stale FreeCAD锁=$($lock.FullName)，PID=$stalePid（进程不存在）" "WARNING"
    }
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Stop-WithMessage "未找到 Python。请安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。"
    }
    $python = $pythonCommand.Source
}
Write-LauncherLog "Python路径=$python"
$preexistingHealth = Sync-BackendPidState

Write-Step "检查 Python、FreeCAD、依赖、端口和插件"
$checkArgs = @((Join-Path $projectRoot "check_environment.py"), "--json", "--appdata", $env:APPDATA, "--port", "$Port")
if ($FreeCADBin) { $checkArgs += @("--freecad", $FreeCADBin) }
$environmentOutput = & $python @checkArgs 2>&1
if ($LASTEXITCODE -ne 0 -or -not $environmentOutput) {
    Stop-WithMessage "环境检查程序未能正常运行：$(($environmentOutput | Out-String).Trim())"
}
try {
    $environment = (($environmentOutput | Out-String).Trim()) | ConvertFrom-Json
} catch {
    Stop-WithMessage "环境检查输出无法解析：$($_.Exception.Message)；输出=$(($environmentOutput | Out-String).Trim())"
}
if (-not $environment.python.ok) {
    Stop-WithMessage "Python 版本过低：$($environment.python.version)。需要 Python 3.10 或更高版本。"
}
if (-not $environment.freecad.ok) {
    Stop-WithMessage "未找到 FreeCAD GUI。请安装 FreeCAD，或在 .env 中设置 FREECAD_GUI=D:\路径\FreeCAD.exe。"
}
if (-not $environment.dependencies.ok) {
    Write-Host "缺少以下 Python 依赖：" -ForegroundColor Yellow
    $environment.dependencies.missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    $missingText = ($environment.dependencies.missing -join ", ")
    Stop-WithMessage "Python 依赖缺失：$missingText。请执行：`"$python`" -m pip install -r requirements.txt"
}
Write-LauncherLog "FreeCAD路径=$($environment.freecad.path)"
Write-LauncherLog "FreeCAD版本=$($environment.freecad.version)"
Write-LauncherLog "端口$Port 初始状态=$($environment.port.state)"
if ($environment.port.state -eq "occupied" -and -not $preexistingHealth) {
    Stop-WithMessage "端口 $Port 已被其他程序占用，而且不是 AI CAD Backend。请关闭占用程序后重试。"
}
$freecadExe = $environment.freecad.path
$env:AICAD_BACKEND_WS = "ws://127.0.0.1:$Port/ws/freecad"
Write-Host "  Python $($environment.python.version)" -ForegroundColor Green
Write-Host "  $($environment.freecad.version)" -ForegroundColor Green
Write-Host "  FreeCAD: $freecadExe" -ForegroundColor DarkGray

Write-Step "安装或更新 AI CAD Copilot Workbench"
$installOutput = & $python (Join-Path $projectRoot "scripts\install_freecad_addon.py") --json --appdata $env:APPDATA 2>&1
if ($LASTEXITCODE -ne 0 -or -not $installOutput) {
    Stop-WithMessage "FreeCAD 插件安装失败：$(($installOutput | Out-String).Trim())"
}
try {
    $installation = (($installOutput | Out-String).Trim()) | ConvertFrom-Json
} catch {
    Stop-WithMessage "FreeCAD 插件安装结果无法解析：$($_.Exception.Message)"
}
$requiredAddonFiles = @("Init.py", "InitGui.py", "Workbench.py")
foreach ($requiredFile in $requiredAddonFiles) {
    $requiredPath = Join-Path $installation.target $requiredFile
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        Stop-WithMessage "FreeCAD 插件安装失败：缺少 $requiredPath（可能多套了一层目录）"
    }
}
Write-LauncherLog "Add-on路径=$($installation.target)"
Write-LauncherLog "Add-on状态=$($installation.action)，Init.py/InitGui.py/Workbench.py=完整"
if ($installation.action -eq "unchanged") {
    Write-Host "  插件已是最新版本" -ForegroundColor Green
} else {
    $installVerb = if ($installation.action -eq "updated") { "更新" } else { "安装" }
    Write-Host "  插件已$installVerb：$($installation.target)" -ForegroundColor Green
}

if (-not $NoShortcuts) {
    Write-Step "创建或更新桌面快捷方式"
    $shortcutOutput = & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $projectRoot "scripts\create_shortcuts.ps1") `
        -ProjectRoot $projectRoot -IconPath $freecadExe 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $shortcutOutput) {
        Stop-WithMessage "桌面快捷方式创建失败：$(($shortcutOutput | Out-String).Trim())"
    }
    Write-LauncherLog "桌面快捷方式=$((($shortcutOutput | Out-String).Trim()))"
}

# A healthy process is not proof that the durable Windows host exists.  Older
# launchers skipped Task Scheduler registration whenever port 8000 happened to
# be healthy; that made the site disappear after the temporary parent exited.
# Always repair the persistent host definition before reusing a live process.
$taskBeforeStart = Get-BackendTaskStatus
if (-not $taskBeforeStart.task_exists -or -not $taskBeforeStart.config_matches -or
        [string]$taskBeforeStart.action -ne [string]$python -or
        [string]$taskBeforeStart.working_directory -ne [string]$projectRoot) {
    Write-Step "修复独立 Backend 宿主"
    try {
        $taskRepair = Invoke-BackendTaskStart
        Write-LauncherLog "计划任务已自愈：exists=$($taskRepair.task_exists)，config=$($taskRepair.config_matches)，action=$($taskRepair.action)，cwd=$($taskRepair.working_directory)"
    } catch {
        Stop-WithMessage (Get-BackendFailureReport "计划任务缺失或配置过期，自动重建失败：$($_.Exception.Message)")
    }
} else {
    Write-LauncherLog "计划任务定义有效：$($taskBeforeStart.task_path)，action=$($taskBeforeStart.action)，cwd=$($taskBeforeStart.working_directory)"
}

$health = $preexistingHealth
if (-not $health) {
    Write-Step "启动 AI CAD Backend"
    $backendLog = Join-Path $logDir "backend.log"
    try {
        $launchResult = Invoke-BackendTaskStart
    } catch {
        Write-LauncherLog "首次计划任务启动失败，自动重新注册后重试：$($_.Exception.Message)" "WARNING"
        try {
            $launchResult = Invoke-BackendTaskStart
        } catch {
            Stop-WithMessage (Get-BackendFailureReport $_.Exception.Message)
        }
    }
    Write-LauncherLog "Backend启动命令=$($launchResult.command)"
    Write-LauncherLog "Backend独立模式=$($launchResult.detach_mode)"
    Write-LauncherLog "Backend计划任务=$($launchResult.task_path)，state=$($launchResult.task_state)，parent=$($launchResult.parent_authority)"
    Write-LauncherLog "Codex Job inheritance=$($launchResult.codex_job_inheritance)"
    $waitStarted = Get-Date
    $deadline = $waitStarted.AddSeconds($BackendTimeoutSeconds)
    $nextProgress = 0
    $retriedStoppedTask = $false
    do {
        Start-Sleep -Milliseconds 500
        $listeningPid = Get-ListeningPid
        $health = Get-AICadHealth
        $pidFileValue = Get-BackendPidFileValue
        $backendPid = if ($health) { [int]$health.pid } else { 0 }
        $elapsedSeconds = [int][Math]::Floor(((Get-Date) - $waitStarted).TotalSeconds)
        if ($elapsedSeconds -ge $nextProgress -and -not $health) {
            $taskStatus = Get-BackendTaskStatus
            $portText = if ($listeningPid) { "LISTENING" } else { "等待监听" }
            Write-Host ("  正在准备后台服务... {0}/{1} 秒" -f `
                $elapsedSeconds, $BackendTimeoutSeconds) -ForegroundColor DarkGray
            Write-LauncherLog "Backend等待进度=$elapsedSeconds/$BackendTimeoutSeconds 秒，Task=$($taskStatus.task_state)，8000=$portText，health=waiting"
            $nextProgress += 2
            if (-not $retriedStoppedTask -and $elapsedSeconds -ge 2 -and
                    $taskStatus.task_exists -and $taskStatus.task_state -notin @("Running", "Queued")) {
                $retriedStoppedTask = $true
                Write-Host "  计划任务提前停止，正在自动修复并重试一次..." -ForegroundColor Yellow
                Write-LauncherLog "计划任务提前停止，state=$($taskStatus.task_state)，last=$($taskStatus.last_task_result_hex)；重新注册并重试" "WARNING"
                try {
                    $launchResult = Invoke-BackendTaskStart
                } catch {
                    Write-LauncherLog "计划任务自动重试失败：$($_.Exception.Message)" "ERROR"
                }
            }
        }
    } until (($backendPid -gt 0 -and $listeningPid -eq $backendPid -and
              $pidFileValue -eq $backendPid -and
              (Get-Process -Id $backendPid -ErrorAction SilentlyContinue)) -or
             (Get-Date) -ge $deadline)
    if (-not $health -or $listeningPid -ne $backendPid -or $pidFileValue -ne $backendPid -or
            -not (Get-Process -Id $backendPid -ErrorAction SilentlyContinue)) {
        Stop-WithMessage (Get-BackendFailureReport "$BackendTimeoutSeconds 秒内未同时满足 8000 LISTENING、/api/health=200、PID文件/health/listener一致。")
    }
    Add-Content -LiteralPath $backendLog -Value "[$(Get-Date -Format o)] [INFO] health状态=HTTP 200，listener PID=$listeningPid" -Encoding UTF8
    Write-Host "  Backend OK" -ForegroundColor Green
} else {
    Write-Step "复用已运行的 AI CAD Backend"
    $listeningPid = Get-ListeningPid
    if (-not $listeningPid -or [int]$health.pid -ne $listeningPid) {
        Stop-WithMessage "现有 Backend 状态不一致：health PID=$($health.pid)，8000 listener PID=$listeningPid。"
    }
    $pidFileValue = [int](Get-Content -LiteralPath (Join-Path $logDir "backend.pid") -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidFileValue -ne $listeningPid) {
        Stop-WithMessage "现有 Backend PID管理不一致：pid文件=$pidFileValue，health/listener=$listeningPid。"
    }
    Write-Host "  Backend OK" -ForegroundColor Green
}
Write-LauncherLog "Backend PID=$($health.pid)"
Write-LauncherLog "端口$Port 状态=LISTENING，GET /api/health=成功"

Write-Step "确认网站首页可用"
if (-not (Get-WebsiteReady)) {
    Stop-WithMessage "Backend 已监听但网站首页未返回有效 HTML。已停止后续流程，不会打开浏览器。"
}
Write-Host "  Website Ready" -ForegroundColor Green
Write-LauncherLog "网站状态=HTTP 200，Content-Type=text/html，Website Ready"

$freecadLog = Join-Path $logDir "freecad.log"
$freecadStatus = Get-FreeCADStatus
Quarantine-StaleFreeCADRecovery
if ((-not $freecadStatus -or -not $freecadStatus.freecad_online) -and
        (Get-Process -Name "FreeCAD" -ErrorAction SilentlyContinue)) {
    Write-Step "等待已运行的 FreeCAD 重新连接 Backend"
    $reconnectDeadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $freecadStatus = Get-FreeCADStatus
    } until (($freecadStatus -and $freecadStatus.freecad_online) -or
             (Get-Date) -ge $reconnectDeadline)
    if (-not $freecadStatus -or -not $freecadStatus.freecad_online) {
        Stop-WithMessage "检测到已运行但未连接的 FreeCAD。为防止多个实例争抢 Bridge，未启动第二个 FreeCAD；请保存并关闭原窗口后再次双击。"
    }
}
if (-not $freecadStatus -or -not $freecadStatus.freecad_online) {
    Write-Step "启动 FreeCAD GUI"
    $moduleRoot = Split-Path $installation.target -Parent
    $freecadArgs = @("-M", ('"{0}"' -f $installation.target), "-P", ('"{0}"' -f $moduleRoot))
    if ($FreeCADUserConfig) {
        New-Item -ItemType Directory -Path (Split-Path $FreeCADUserConfig -Parent) -Force | Out-Null
        $freecadArgs += @("-u", ('"{0}"' -f $FreeCADUserConfig))
    }
    if ($FreeCADSystemConfig) {
        New-Item -ItemType Directory -Path (Split-Path $FreeCADSystemConfig -Parent) -Force | Out-Null
        $freecadArgs += @("-s", ('"{0}"' -f $FreeCADSystemConfig))
    }
    Set-Content -LiteralPath $freecadLog -Value "" -Encoding UTF8
    $freecadArgs += @("--log-file", ('"{0}"' -f $freecadLog))
    $freecad = Start-Process -FilePath $freecadExe -ArgumentList $freecadArgs `
        -WorkingDirectory (Split-Path $freecadExe) -PassThru
    Write-LauncherLog "FreeCAD PID=$($freecad.Id)"
    Write-LauncherLog "FreeCAD参数=$($freecadArgs -join ' ')"
    Write-Host "  FreeCAD 已启动（PID $($freecad.Id)）" -ForegroundColor Green
    $deadline = (Get-Date).AddSeconds($FreeCADTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 300
        if ($freecad.HasExited) {
            Stop-WithMessage "FreeCAD 提前退出。请从命令行运行 FreeCAD 查看启动错误。"
        }
        $freecadStatus = Get-FreeCADStatus
    } until (($freecadStatus -and $freecadStatus.freecad_online) -or (Get-Date) -ge $deadline)
    if (-not $freecadStatus -or -not $freecadStatus.freecad_online) {
        $freecadDiagnostic = Get-LogDiagnostic $freecadLog
        Stop-WithMessage "FreeCAD 插件加载失败：Workbench/Bridge 在 $FreeCADTimeoutSeconds 秒内未连接。$freecadDiagnostic"
    }
} else {
    Write-Step "复用已连接的 FreeCAD GUI"
}

$statusDeadline = (Get-Date).AddSeconds(8)
do {
    $freecadStatus = Get-FreeCADStatus
    if ($freecadStatus.workbench_registered -and $freecadStatus.active_workbench -eq "AICADCopilotWorkbench" -and $freecadStatus.dock_visible -and $freecadStatus.model_tree_visible) { break }
    Start-Sleep -Milliseconds 250
} until ((Get-Date) -ge $statusDeadline)

Write-LauncherLog "Workbench注册状态=$($freecadStatus.workbench_registered)"
Write-LauncherLog "Workbench加载状态=$($freecadStatus.active_workbench)"
Write-LauncherLog "Bridge连接状态=$($freecadStatus.freecad_online)"
Write-LauncherLog "Dock Panel状态=$($freecadStatus.dock_visible)"
Write-LauncherLog "模型树面板状态=$($freecadStatus.model_tree_visible)"

if ($freecadStatus.active_modal) {
    Stop-WithMessage "FreeCAD 被模态窗口阻塞：$($freecadStatus.active_modal)。请处理该窗口后重试。"
}
if (-not $freecadStatus.workbench_registered) {
    $freecadDiagnostic = Get-LogDiagnostic $freecadLog
    Stop-WithMessage "FreeCAD 插件加载失败：未找到 AI CAD Copilot Workbench。$freecadDiagnostic"
}
if (-not $freecadStatus.freecad_online) {
    Stop-WithMessage "FreeCAD Bridge 连接失败：Backend /api/freecad/status 未显示 connected。"
}
if ($freecadStatus.active_workbench -ne "AICADCopilotWorkbench") {
    Stop-WithMessage "FreeCAD Workbench 自动激活失败：当前为 $($freecadStatus.active_workbench)"
}
if (-not $freecadStatus.dock_visible) {
    Stop-WithMessage "FreeCAD 插件加载失败：AI CAD Copilot Dock Panel 未显示。"
}
if (-not $freecadStatus.model_tree_visible) {
    Stop-WithMessage "FreeCAD 界面初始化失败：参数化模型树面板未显示。"
}
Write-Host "  FreeCAD OK" -ForegroundColor Green
Write-Host "  AI Bridge Connected" -ForegroundColor Green

if (-not $NoBrowser) {
    Write-Step "打开 AI 聊天入口"
    try {
        Start-Process "http://127.0.0.1:$Port" | Out-Null
        Write-LauncherLog "浏览器打开状态=成功，URL=http://127.0.0.1:$Port"
    } catch {
        Stop-WithMessage "浏览器打开失败：$($_.Exception.Message)"
    }
} else {
    Write-LauncherLog "浏览器打开状态=跳过（NoBrowser）"
}

$elapsed = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 2)
Write-Host "`nAI CAD Copilot 已就绪（$elapsed 秒）" -ForegroundColor Green
Write-Host "  FreeCAD Connected: $($freecadStatus.freecad_online)"
Write-Host "  Workbench Registered: $($freecadStatus.workbench_registered)"
Write-Host "  Workbench: $($freecadStatus.active_workbench)"
Write-Host "  Dock Panel: $($freecadStatus.dock_visible)"
Write-Host "  Model Tree: $($freecadStatus.model_tree_visible)"
Write-Host "  AI 入口: http://127.0.0.1:$Port"
Write-Host "`n现在可以输入：创建一个300mm阶梯轴" -ForegroundColor Cyan
Write-LauncherLog "启动完成，耗时=$elapsed 秒"
Write-LauncherLog "Launcher即将退出；Backend由Windows Task Scheduler继续托管"

exit 0
