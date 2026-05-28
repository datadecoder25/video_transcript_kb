@echo off
REM Transcript Knowledge Base - Windows Installer (wrapper)
REM Double-click this file or run from Command Prompt

echo ==============================================
echo  Transcript Knowledge Base - Installer
echo ==============================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"

echo.
pause
