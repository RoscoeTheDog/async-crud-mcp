@echo off
setlocal enabledelayedexpansion

:: ============================================
::   async-crud-mcp Setup
:: ============================================
:: Unified installer/uninstaller script
:: Calls installer.py which presents an interactive menu

:: Check admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Find Python
set "PYTHON_EXE="
where python >nul 2>&1 && set "PYTHON_EXE=python"
where python3 >nul 2>&1 && set "PYTHON_EXE=python3"

if not defined PYTHON_EXE (
    echo [ERROR] Python not found in PATH
    echo Please install Python 3.10+ from https://python.org
    echo.
    echo ========================================
    echo Press any key to close...
    echo ========================================
    pause >nul
    exit /b 1
)

:: Verify Python version
for /f "tokens=2 delims= " %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PY_VERSION=%%v"
echo Found Python %PY_VERSION%

:: Run Python installer (no args = interactive mode)
"%PYTHON_EXE%" "%~dp0installer.py" %*
:: Python script handles its own "Press Enter to close..." prompt
exit /b %errorlevel%
