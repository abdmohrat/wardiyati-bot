@echo off

:: Get the directory where this batch file is located.
set "BASE_DIR=%~dp0"
set "BOT_SCRIPT_PATH=%BASE_DIR%\bot.py"
set "LOCAL_BROWSERS=%BASE_DIR%\ms-playwright"

:: Check if python is in the user's PATH
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo =================================================================
    echo  ERROR: Python is not installed or not added to PATH.
    echo =================================================================
    echo.
    echo  Please run "FIRST TIME SETUP.bat" first.
    echo.
    pause
    exit /b
)

:: Check if setup was completed
if not exist "%LOCAL_BROWSERS%" (
    echo ===============================================================
    echo   ⚠️  Setup Required
    echo ===============================================================
    echo.
    echo   Please run "FIRST TIME SETUP.bat" first to install
    echo   the required components.
    echo.
    pause
    exit /b
)

:: Set environment and launch the bot
set PLAYWRIGHT_BROWSERS_PATH=%LOCAL_BROWSERS%
python "%BOT_SCRIPT_PATH%"