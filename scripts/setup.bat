@echo off
setlocal enabledelayedexpansion

:: async-crud-mcp Windows Installer Wrapper
:: Detects Python 3.12+ and delegates to installer.py

echo [SETUP] async-crud-mcp Windows Installer
echo.

:: Try python from PATH
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python --version 2>nul | findstr /R "Python 3\.1[2-9]\." >nul
    if !ERRORLEVEL! EQU 0 (
        set PYTHON=python
        goto :found_python
    )
)

:: Try python3 from PATH
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python3 --version 2>nul | findstr /R "Python 3\.1[2-9]\." >nul
    if !ERRORLEVEL! EQU 0 (
        set PYTHON=python3
        goto :found_python
    )
)

:: Try py launcher with -3.12
py -3.12 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON=py -3.12
    goto :found_python
)

:: Try common install locations
set PYTHON_LOCATIONS=C:\Python312\python.exe C:\Python313\python.exe "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

for %%P in (%PYTHON_LOCATIONS%) do (
    if exist %%P (
        %%P --version 2>nul | findstr /R "Python 3\.1[2-9]\." >nul
        if !ERRORLEVEL! EQU 0 (
            set PYTHON=%%P
            goto :found_python
        )
    )
)

:: Python not found
echo [ERROR] Python 3.12 or newer not found
echo.
echo Please install Python 3.12+ from:
echo https://www.python.org/downloads/
echo.
echo Make sure to check "Add Python to PATH" during installation.
pause
exit /b 1

:found_python
echo [OK] Found Python: %PYTHON%
%PYTHON% --version
echo.

:: Delegate to installer.py
"%PYTHON%" "%~dp0installer.py" %*
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% NEQ 0 (
    echo.
    echo [ERROR] Installer exited with code %EXIT_CODE%
    pause
)

endlocal
exit /b %EXIT_CODE%
