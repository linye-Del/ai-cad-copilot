[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [string]$IconPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop) { throw "无法找到当前用户桌面目录" }

$shell = New-Object -ComObject WScript.Shell

function Set-Shortcut([string]$Name, [string]$Target, [string]$Description, [string]$Icon) {
    $path = Join-Path $desktop $Name
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.Description = $Description
    if ($Icon) { $shortcut.IconLocation = "$Icon,0" }
    $shortcut.Save()
    return $path
}

$startIcon = if ($IconPath -and (Test-Path -LiteralPath $IconPath)) { $IconPath } else { "$env:SystemRoot\System32\shell32.dll" }
$stopIcon = "$env:SystemRoot\System32\shell32.dll"
$start = Set-Shortcut "AI CAD Copilot.lnk" (Join-Path $ProjectRoot "start_ai_cad.bat") `
    "启动 AI CAD Copilot、FreeCAD 和 AI 聊天入口" $startIcon
$stop = Set-Shortcut "Stop AI CAD Copilot.lnk" (Join-Path $ProjectRoot "stop_ai_cad.bat") `
    "安全停止 AI CAD Copilot Backend，并请求关闭 FreeCAD" $stopIcon

[ordered]@{
    ok = $true
    desktop = $desktop
    start_shortcut = $start
    stop_shortcut = $stop
} | ConvertTo-Json -Compress
