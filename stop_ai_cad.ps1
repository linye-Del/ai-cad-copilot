[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$KeepFreeCAD,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$logDir = Join-Path $projectRoot "logs"
$pidFile = Join-Path $logDir "backend.pid"
$stopFile = Join-Path $logDir "backend.stop"
$taskHelper = Join-Path $projectRoot "scripts\backend_task.ps1"
$stopLog = Join-Path $logDir "stop.log"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-StopLog([string]$Message, [string]$Level = "INFO") {
    Add-Content -LiteralPath $stopLog -Encoding UTF8 -Value `
        ("[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Level, $Message)
}

Write-StopLog "===== Stop AI CAD Copilot start ====="

function Get-Health {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    } catch {
        return $null
    }
}

function Get-ListeningPid {
    $pattern = "^\s*TCP\s+127\.0\.0\.1:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p TCP 2>$null)) {
        if ($line -match $pattern) { return [int]$Matches[1] }
    }
    return $null
}

if (-not $KeepFreeCAD) {
    $freecadProcesses = @(Get-Process -Name "FreeCAD" -ErrorAction SilentlyContinue)
    $windowShell = New-Object -ComObject WScript.Shell
    foreach ($process in $freecadProcesses) {
        try {
            if (-not $process.HasExited) {
                $null = $process.CloseMainWindow()
                $process.Refresh()
                if (-not $process.HasExited -and $process.MainWindowHandle -ne 0) {
                    $null = $windowShell.AppActivate($process.Id)
                    Start-Sleep -Milliseconds 200
                    $windowShell.SendKeys("%{F4}")
                }
            }
        } catch {
            # FreeCAD can exit between HasExited/MainWindowHandle reads. That race
            # means the requested outcome was already reached, not a stop failure.
            Write-StopLog "FreeCAD PID=$($process.Id) 关闭期间已退出或句柄失效：$($_.Exception.Message)" "WARNING"
        }
    }
    if ($freecadProcesses.Count -gt 0) {
        Write-StopLog "请求关闭 FreeCAD，count=$($freecadProcesses.Count)，pids=$($freecadProcesses.Id -join ',')"
        Write-Host "已请求 FreeCAD 正常退出；如有未保存模型，请在窗口中确认保存。" -ForegroundColor Yellow
        $freecadDeadline = (Get-Date).AddSeconds(12)
        do {
            Start-Sleep -Milliseconds 300
            $remainingFreeCAD = @(Get-Process -Name "FreeCAD" -ErrorAction SilentlyContinue)
        } until ($remainingFreeCAD.Count -eq 0 -or (Get-Date) -ge $freecadDeadline)
        foreach ($process in $remainingFreeCAD) {
            try {
                if (($process.MainWindowHandle -eq 0 -and -not $process.MainWindowTitle) -or
                        $process.MainWindowTitle -eq "FreeCAD") {
                    Stop-Process -Id $process.Id -Force
                    Write-Host "已清理无打开文档的 FreeCAD 残留进程（PID $($process.Id)）。" -ForegroundColor DarkGray
                } else {
                    Write-Warning "FreeCAD 仍等待用户处理保存窗口（PID $($process.Id)），未强制关闭。"
                }
            } catch {
                Write-StopLog "检查FreeCAD残留 PID=$($process.Id) 时进程已退出：$($_.Exception.Message)" "WARNING"
            }
        }
    }
    Write-StopLog "FreeCAD关闭阶段完成，remaining=$(@(Get-Process -Name 'FreeCAD' -ErrorAction SilentlyContinue).Count)"
}

$health = Get-Health
$listenerPid = Get-ListeningPid
$managedPid = $null
if ($health -and $health.ok -and $health.service -eq "ai-cad-copilot" -and
        $listenerPid -eq [int]$health.pid) {
    $managedPid = [int]$health.pid
}

# Health may be temporarily unavailable while FreeCAD disconnects. A matching PID
# file + listener + backend_host command line is still strong ownership evidence.
if (-not $managedPid -and $listenerPid) {
    $filePid = 0
    $rawPid = if (Test-Path -LiteralPath $pidFile) {
        Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    } else { "" }
    if ([int]::TryParse([string]$rawPid, [ref]$filePid) -and $filePid -eq $listenerPid) {
        try {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid" -ErrorAction Stop
            if ($process.CommandLine -like "*scripts\backend_host.py*" -and
                    $process.CommandLine -like "*$projectRoot*") {
                $managedPid = $listenerPid
                Write-StopLog "Health暂不可用；通过PID文件/listener/command line确认Backend，PID=$managedPid" "WARNING"
            }
        } catch {
            Write-StopLog "读取Backend进程命令行失败：$($_.Exception.Message)" "WARNING"
        }
    }
}

Write-StopLog "Backend识别：managed_pid=$managedPid，listener_pid=$listenerPid，health_pid=$($health.pid)"

if ($managedPid) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Set-Content -LiteralPath $stopFile -Value (Get-Date -Format o) -Encoding ASCII
    Write-StopLog "已写入停止请求=$stopFile，PID=$managedPid"
    Write-Host "正在安全关闭 Backend（PID $managedPid）..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 250
        $health = Get-Health
        $listenerPid = Get-ListeningPid
    } until ((-not $health -and -not $listenerPid) -or (Get-Date) -ge $deadline)

    if ($health -or $listenerPid) {
        Write-Warning "Backend 未在 $TimeoutSeconds 秒内正常退出，正在停止 Windows 计划任务。"
        Write-StopLog "Backend未正常退出，调用计划任务Stop，health=$([bool]$health)，listener=$listenerPid" "WARNING"
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $taskHelper -Mode Stop | Out-Null
        Start-Sleep -Seconds 3
        $health = Get-Health
        $listenerPid = Get-ListeningPid
    }
    if ($health -or $listenerPid) {
        Write-StopLog "Backend停止失败，health=$([bool]$health)，listener=$listenerPid" "ERROR"
        throw "Backend 仍在运行；为避免误杀其他进程，未使用 taskkill。请查看 logs\backend.log。"
    }
    Write-Host "Backend 已安全关闭。" -ForegroundColor Green
    Write-StopLog "Backend已安全关闭"
} else {
    Write-Host "Backend 当前未运行。" -ForegroundColor DarkGray
    Write-StopLog "Backend未被识别为运行中，未执行停止" "WARNING"
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
Write-StopLog "===== Stop AI CAD Copilot complete ====="

exit 0
