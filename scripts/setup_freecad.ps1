param(
    [string]$Version = "1.1.3"
)

$ErrorActionPreference = "Stop"
$dest = Join-Path $env:TEMP "FreeCAD_installer.exe"

function Get-FreeCAD {
    $url = "https://github.com/FreeCAD/FreeCAD/releases/download/$Version/FreeCAD_$Version-Windows-x86_64-py311-installer.exe"
    Write-Host "下载 FreeCAD $Version ..." -ForegroundColor Cyan
    Start-BitsTransfer -Source $url -Destination $dest
}

if (-not (Test-Path $dest) -or (Get-Item $dest).Length -lt 100MB) {
    Get-FreeCAD
}

Write-Host "静默安装中（几分钟）..." -ForegroundColor Cyan
Start-Process -FilePath $dest -ArgumentList "/S" -Wait

$cmd = "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe"
if (-not (Test-Path $cmd)) {
    $cmd = (Get-ChildItem "C:\Program Files\FreeCAD*\bin\FreeCADCmd.exe" | Select-Object -First 1).FullName
}
if (Test-Path $cmd) {
    Write-Host "安装完成: $cmd" -ForegroundColor Green
    & $cmd --version
} else {
    Write-Host "未找到 FreeCADCmd.exe，请手动安装后设置 .env 中 FREECAD_BIN" -ForegroundColor Yellow
}