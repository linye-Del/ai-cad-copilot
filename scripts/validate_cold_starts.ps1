param(
    [int]$Rounds = 3,
    [string]$FreeCadPath = $env:FREECAD_GUI
)

$ErrorActionPreference = "Stop"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $project "start_ai_cad.bat"
$logDir = Join-Path $project "logs"
$results = @()
$checkpoints = @(0, 30, 60, 120, 300)

function Get-ListeningPid {
    foreach ($line in (& netstat.exe -ano -p TCP 2>$null)) {
        if ($line -match "^\s*TCP\s+127\.0\.0\.1:8000\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Stop-ProjectProcesses {
    $backendPid = Get-ListeningPid
    if ($backendPid) {
        Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue
    }
    $freecad = @()
    if ($FreeCadPath -and (Test-Path -LiteralPath $FreeCadPath)) {
        $expectedFreeCad = [IO.Path]::GetFullPath($FreeCadPath)
        $freecad = @(Get-Process -Name "FreeCAD" -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and ([IO.Path]::GetFullPath($_.Path) -ieq $expectedFreeCad)
        })
    }
    foreach ($process in $freecad) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    if (Get-ListeningPid) { throw "清理后 8000 端口仍处于 LISTENING" }
}

function Backup-RecoveryLocks([int]$round) {
    $cache = Join-Path $env:TEMP "FreeCAD\v1-1\Cache"
    $backup = Join-Path $logDir ("freecad_recovery_locks_backup_stability_{0:D2}" -f $round)
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    if (-not (Test-Path -LiteralPath $cache)) { return }
    foreach ($file in Get-ChildItem -LiteralPath $cache -Filter "FreeCAD_*.lock" -File) {
        if ($file.FullName.StartsWith($cache, [StringComparison]::OrdinalIgnoreCase)) {
            Move-Item -LiteralPath $file.FullName -Destination (Join-Path $backup $file.Name) -Force
        }
    }
}

function Test-Checkpoint([int]$second, [int]$expectedPid) {
    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 10
    $website = Invoke-WebRequest "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 10
    $listenerPid = Get-ListeningPid
    $processAlive = [bool](Get-Process -Id $expectedPid -ErrorAction SilentlyContinue)
    $websiteReady = ($website.StatusCode -eq 200 -and
        [string]$website.Headers["Content-Type"] -match "text/html" -and
        $website.Content -match "AI CAD Copilot")
    $passed = ($health.ok -and [int]$health.pid -eq $expectedPid -and
        $listenerPid -eq $expectedPid -and $processAlive -and $websiteReady)
    return [pscustomobject]@{
        second = $second
        checked_at = (Get-Date -Format o)
        passed = [bool]$passed
        health_http = 200
        website_http = [int]$website.StatusCode
        health_pid = [int]$health.pid
        listener_pid = [int]$listenerPid
        process_alive = $processAlive
        website_ready = [bool]$websiteReady
    }
}

for ($round = 1; $round -le $Rounds; $round++) {
    Stop-ProjectProcesses
    Backup-RecoveryLocks $round
    if (Get-ListeningPid) { throw "第 $round 轮不是冷启动：8000 已监听" }

    Push-Location $project
    try {
        # Same entry point and working directory as a user double-click.
        & cmd.exe /d /c ('"{0}"' -f $launcher)
        if ($LASTEXITCODE -ne 0) { throw "launcher exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }

    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 10
    $expectedPid = [int]$health.pid
    $status = Invoke-RestMethod "http://127.0.0.1:8000/api/freecad/status" -TimeoutSec 10
    if (-not ($status.freecad_online -and $status.workbench_registered -and
            $status.active_workbench -eq "AICADCopilotWorkbench" -and
            $status.dock_visible -and $status.model_tree_visible -and
            -not $status.active_modal)) {
        throw "第 $round 轮 FreeCAD/Bridge/Workbench/Dock 未达到 Ready"
    }

    $roundStarted = Get-Date
    $samples = @()
    foreach ($checkpoint in $checkpoints) {
        $wait = $checkpoint - [int][Math]::Floor(((Get-Date) - $roundStarted).TotalSeconds)
        if ($wait -gt 0) { Start-Sleep -Seconds $wait }
        $sample = Test-Checkpoint $checkpoint $expectedPid
        $samples += $sample
        if (-not $sample.passed) {
            throw "第 $round 轮 T+$checkpoint 秒存活检查失败"
        }
    }

    $launcherCopy = Join-Path $logDir ("cold_start_stability_{0:D2}_launcher.log" -f $round)
    $backendCopy = Join-Path $logDir ("cold_start_stability_{0:D2}_backend.log" -f $round)
    Copy-Item -LiteralPath (Join-Path $logDir "launcher.log") -Destination $launcherCopy -Force
    Copy-Item -LiteralPath (Join-Path $logDir "backend.log") -Destination $backendCopy -Force
    $results += [pscustomobject]@{
        round = $round
        passed = $true
        backend_pid = $expectedPid
        connected = [bool]$status.freecad_online
        workbench = $status.active_workbench
        dock = [bool]$status.dock_visible
        checkpoints = $samples
        launcher_log = $launcherCopy
        backend_log = $backendCopy
    }
    $results | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $logDir "cold_start_stability_results.json") -Encoding UTF8
}

$results | Format-Table round,passed,backend_pid,connected,workbench,dock -AutoSize
