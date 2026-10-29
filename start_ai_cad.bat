@echo off
chcp 65001 >nul
setlocal
title AI CAD Copilot 2.0
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ai_cad.ps1"
set "AICAD_EXIT=%ERRORLEVEL%"
if not "%AICAD_EXIT%"=="0" (
    echo.
    echo 启动未完成。请根据上方中文提示处理后重试。
    pause
)
exit /b %AICAD_EXIT%
