@echo off
chcp 65001 >nul
setlocal
title Stop AI CAD Copilot
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_ai_cad.ps1"
set "AICAD_EXIT=%ERRORLEVEL%"
if not "%AICAD_EXIT%"=="0" (
    echo.
    echo AI CAD Copilot 未能完全停止，请查看上方提示。
    pause
)
exit /b %AICAD_EXIT%
