[CmdletBinding()]
param(
    [ValidateSet("Start", "Status", "Stop", "Delete")]
    [string]$Mode = "Start",
    [string]$ProjectRoot = "",
    [string]$Python = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$taskFolderPath = "\AI CAD Copilot"
$taskName = "Backend"
$taskPath = "$taskFolderPath\$taskName"
$taskConfigVersion = "3"
$taskDescription = "AI CAD Copilot Backend host; config-version=$taskConfigVersion; managed by the desktop launcher."

function Connect-Scheduler {
    $service = New-Object -ComObject "Schedule.Service"
    $service.Connect()
    return $service
}

function Get-TaskFolder($Service, [switch]$Create) {
    try {
        return $Service.GetFolder($taskFolderPath)
    } catch {
        if (-not $Create) { return $null }
        return $Service.GetFolder("\").CreateFolder($taskFolderPath.TrimStart("\"))
    }
}

function Get-TaskStateName([int]$State) {
    switch ($State) {
        0 { "Unknown" }
        1 { "Disabled" }
        2 { "Queued" }
        3 { "Ready" }
        4 { "Running" }
        default { "State-$State" }
    }
}

function Get-ResultHex([int]$Value) {
    $bytes = [BitConverter]::GetBytes($Value)
    $unsigned = [BitConverter]::ToUInt32($bytes, 0)
    return ("0x{0:X8}" -f $unsigned)
}

function Get-TaskDetails($Task) {
    if ($null -eq $Task) {
        return [ordered]@{
            task_exists = $false
            task_path = $taskPath
            task_state = "Missing"
            config_version = $taskConfigVersion
            config_matches = $false
        }
    }
    $definition = $Task.Definition
    $instances = @($Task.GetInstances(0))
    $action = if ($definition.Actions.Count -gt 0) { $definition.Actions.Item(1) } else { $null }
    $lastResult = [int]$Task.LastTaskResult
    return [ordered]@{
        task_exists = $true
        task_path = $taskPath
        task_state = Get-TaskStateName ([int]$Task.State)
        scheduler_instance_count = $instances.Count
        scheduler_engine_pids = @($instances | ForEach-Object { [int]$_.EnginePID })
        last_run_time = [string]$Task.LastRunTime
        last_task_result = $lastResult
        last_task_result_hex = Get-ResultHex $lastResult
        principal_user = [string]$definition.Principal.UserId
        principal_logon_type = [int]$definition.Principal.LogonType
        principal_run_level = [int]$definition.Principal.RunLevel
        action = if ($action) { [string]$action.Path } else { "" }
        arguments = if ($action) { [string]$action.Arguments } else { "" }
        working_directory = if ($action) { [string]$action.WorkingDirectory } else { "" }
        config_version = $taskConfigVersion
        config_matches = ([string]$definition.RegistrationInfo.Description -eq $taskDescription)
    }
}

function Write-Result($Value) {
    $Value | ConvertTo-Json -Compress -Depth 6
}

$scheduler = Connect-Scheduler

if ($Mode -eq "Start") {
    if (-not $ProjectRoot -or -not $Python) {
        throw "Start mode requires ProjectRoot and Python"
    }
    $ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    $Python = [System.IO.Path]::GetFullPath($Python)
    $hostScript = Join-Path $ProjectRoot "scripts\backend_host.py"
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Python does not exist: $Python"
    }
    if (-not (Test-Path -LiteralPath $hostScript -PathType Leaf)) {
        throw "Backend host does not exist: $hostScript"
    }

    $folder = Get-TaskFolder $scheduler -Create
    $definition = $scheduler.NewTask(0)
    $definition.RegistrationInfo.Author = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $definition.RegistrationInfo.Description = $taskDescription

    $definition.Principal.UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $definition.Principal.LogonType = 3  # TASK_LOGON_INTERACTIVE_TOKEN
    $definition.Principal.RunLevel = 0  # TASK_RUNLEVEL_LUA

    $definition.Settings.Enabled = $true
    $definition.Settings.AllowDemandStart = $true
    $definition.Settings.StartWhenAvailable = $true
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.ExecutionTimeLimit = "PT0S"
    $definition.Settings.MultipleInstances = 2  # TASK_INSTANCES_IGNORE_NEW
    $definition.Settings.RestartCount = 3
    $definition.Settings.RestartInterval = "PT1M"
    $definition.Settings.IdleSettings.StopOnIdleEnd = $false
    $definition.Settings.IdleSettings.RestartOnIdle = $false

    # Recover automatically after Windows logoff/reboot. The desktop launcher still
    # performs the authoritative health check before opening FreeCAD or the browser.
    $logonTrigger = $definition.Triggers.Create(9)  # TASK_TRIGGER_LOGON
    $logonTrigger.UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $logonTrigger.Delay = "PT5S"

    $action = $definition.Actions.Create(0)  # TASK_ACTION_EXEC
    $action.Path = $Python
    $action.WorkingDirectory = $ProjectRoot
    $action.Arguments = ('-u "{0}" --project-root "{1}" --host {2} --port {3} --host-mode scheduled-task --task-name "{4}" --creation-flags "Task Scheduler / InteractiveToken"' -f `
        $hostScript, $ProjectRoot, $HostAddress, $Port, $taskPath)

    $registered = $folder.RegisterTaskDefinition(
        $taskName,
        $definition,
        6,      # TASK_CREATE_OR_UPDATE
        $null,
        $null,
        3,      # TASK_LOGON_INTERACTIVE_TOKEN
        $null
    )
    if ([int]$registered.State -ne 4) {
        $null = $registered.Run($null)
    }
    Start-Sleep -Milliseconds 500
    $registered = $folder.GetTask($taskName)
    $details = Get-TaskDetails $registered
    $result = [ordered]@{
        ok = $true
        mode = "windows-scheduled-task"
        parent_authority = "Windows Task Scheduler Service"
        codex_job_inheritance = $false
    }
    foreach ($key in $details.Keys) { $result[$key] = $details[$key] }
    Write-Result $result
    exit 0
}

$folder = Get-TaskFolder $scheduler
if ($null -eq $folder) {
    Write-Result ([ordered]@{ ok = $true; mode = "windows-scheduled-task"; task_path = $taskPath; task_state = "Missing" })
    exit 0
}

try {
    $task = $folder.GetTask($taskName)
} catch {
    $task = $null
}

if ($Mode -eq "Status") {
    $details = Get-TaskDetails $task
    $result = [ordered]@{ ok = $true }
    foreach ($key in $details.Keys) { $result[$key] = $details[$key] }
    Write-Result $result
    exit 0
}

if ($Mode -eq "Stop") {
    if ($null -ne $task -and [int]$task.State -eq 4) {
        $task.Stop(0)
    }
    Write-Result ([ordered]@{ ok = $true; task_path = $taskPath; task_state = "StopRequested" })
    exit 0
}

if ($Mode -eq "Delete") {
    if ($null -ne $task -and [int]$task.State -eq 4) {
        $task.Stop(0)
    }
    if ($null -ne $task) {
        $folder.DeleteTask($taskName, 0)
    }
    Write-Result ([ordered]@{ ok = $true; task_path = $taskPath; task_state = "Deleted" })
    exit 0
}
