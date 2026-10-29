[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int[]]$Checkpoints = @(0, 30, 60, 300, 900),
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$startBat = Join-Path $projectRoot "start_ai_cad.bat"
$stopBat = Join-Path $projectRoot "stop_ai_cad.bat"
$resultPath = Join-Path $projectRoot "logs\user_launch_validation.json"

function Get-ListeningPid {
    $pattern = "^\s*TCP\s+127\.0\.0\.1:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p TCP 2>$null)) {
        if ($line -match $pattern) { return [int]$Matches[1] }
    }
    return $null
}

function Test-UserState([int]$Elapsed, [int]$ExpectedPid) {
    $health = $null
    $status = $null
    $website = $null
    try { $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 5 } catch {}
    try { $status = Invoke-RestMethod "http://127.0.0.1:$Port/api/freecad/status" -TimeoutSec 5 } catch {}
    try { $website = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5 } catch {}
    $listener = Get-ListeningPid
    $pidFileValue = 0
    $pidFile = Join-Path $projectRoot "logs\backend.pid"
    if (Test-Path -LiteralPath $pidFile) {
        [int]::TryParse([string](Get-Content $pidFile | Select-Object -First 1), [ref]$pidFileValue) | Out-Null
    }
    $healthPid = if ($health) { [int]$health.pid } else { 0 }
    return [ordered]@{
        elapsed_seconds = $Elapsed
        checked_at = Get-Date -Format o
        health_200 = [bool]($health -and $health.ok -eq $true)
        website_200 = [bool]($website -and $website.StatusCode -eq 200 -and $website.Content -match "AI CAD Copilot")
        listener_pid = $listener
        health_pid = $healthPid
        pid_file = $pidFileValue
        pid_unchanged = [bool]($ExpectedPid -gt 0 -and $healthPid -eq $ExpectedPid)
        process_exists = [bool]($healthPid -gt 0 -and (Get-Process -Id $healthPid -ErrorAction SilentlyContinue))
        freecad_connected = [bool]($status -and $status.freecad_online)
        workbench_registered = [bool]($status -and $status.workbench_registered)
        dock_visible = [bool]($status -and $status.dock_visible)
        passed = [bool]($health -and $website -and $listener -eq $healthPid -and
                        $pidFileValue -eq $healthPid -and $healthPid -eq $ExpectedPid -and
                        (Get-Process -Id $healthPid -ErrorAction SilentlyContinue) -and
                        $status.freecad_online -and $status.workbench_registered -and
                        $status.dock_visible)
    }
}

Write-Host "清理旧实例（仅调用普通用户停止入口）..." -ForegroundColor Cyan
& $stopBat
if ($LASTEXITCODE -ne 0) { throw "stop_ai_cad.bat failed with exit code $LASTEXITCODE" }
Start-Sleep -Seconds 2
if (Get-ListeningPid) { throw "冷启动前端口 $Port 仍在监听" }

Write-Host "仅调用普通用户入口：$startBat" -ForegroundColor Cyan
$launchStarted = Get-Date
& $startBat
if ($LASTEXITCODE -ne 0) { throw "start_ai_cad.bat failed with exit code $LASTEXITCODE" }
$launcherExited = Get-Date

$initialHealth = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 10
$expectedPid = [int]$initialHealth.pid
$checks = @()
foreach ($checkpoint in ($Checkpoints | Sort-Object -Unique)) {
    $target = $launcherExited.AddSeconds($checkpoint)
    $remaining = ($target - (Get-Date)).TotalSeconds
    if ($remaining -gt 0) { Start-Sleep -Seconds ([int][Math]::Ceiling($remaining)) }
    $check = Test-UserState $checkpoint $expectedPid
    $checks += $check
    Write-Host ("T+{0}s health={1} website={2} pid={3} connected={4} PASS={5}" -f `
        $checkpoint, $check.health_200, $check.website_200, $check.health_pid,
        $check.freecad_connected, $check.passed)
    if (-not $check.passed) { break }
}

$taskStatusRaw = & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $projectRoot "scripts\backend_task.ps1") -Mode Status
$taskStatus = (($taskStatusRaw | Out-String).Trim()) | ConvertFrom-Json
$lifecyclePath = Join-Path $projectRoot "logs\backend.lifecycle.json"
$lifecycle = if (Test-Path $lifecyclePath) {
    Get-Content $lifecyclePath -Raw | ConvertFrom-Json
} else { $null }

$passed = ($checks.Count -eq ($Checkpoints | Sort-Object -Unique).Count -and
           @($checks | Where-Object { -not $_.passed }).Count -eq 0)
$result = [ordered]@{
    passed = $passed
    launch_started_at = $launchStarted.ToString("o")
    launcher_exited_at = $launcherExited.ToString("o")
    launcher_exit_proved = $true
    start_entry = $startBat
    direct_uvicorn_used = $false
    expected_pid = $expectedPid
    task_status = $taskStatus
    lifecycle = $lifecycle
    checks = $checks
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resultPath -Encoding UTF8

if (-not $KeepRunning) {
    & $stopBat
}
if (-not $passed) { throw "普通用户独立启动存活验收失败，详见 $resultPath" }
Write-Host "普通用户独立启动存活验收 PASS：$resultPath" -ForegroundColor Green
