@echo off
title Wardyati Bot - First Time Setup

:: Get the directory where this batch file is located.
set "BASE_DIR=%~dp0"
set "LOCAL_BROWSERS=%BASE_DIR%\ms-playwright"

echo ===============================================================
echo   🤖 Wardyati Bot - First Time Setup
echo ===============================================================
echo.
echo   This will install the required components for the bot.
echo   This only needs to be done ONCE.
echo.
echo   What will be installed:
echo   - Python libraries (playwright, customtkinter)
echo   - Chromium browser (local installation)
echo.
echo   This may take 2-5 minutes depending on your internet speed.
echo.
pause

:: Check if python is in the user's PATH
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo =================================================================
    echo  ERROR: Python is not installed or not added to PATH.
    echo =================================================================
    echo.
    echo  Please install Python to continue:
    echo  1. Go to: https://www.python.org/downloads/
    echo  2. Download and run the installer.
    echo  3. VERY IMPORTANT: On the first screen of the installer,
    echo     check the box at the bottom that says "Add Python.exe to PATH".
    echo.
    echo  After installing Python, please run this file again.
    echo.
    pause
    exit /b
)

echo ===============================================================
echo   📦 Installing Python libraries...
echo ===============================================================
pip install playwright customtkinter

echo.
echo ===============================================================
echo   🌐 Installing browser components (this may take a while)...
echo ===============================================================
set PLAYWRIGHT_BROWSERS_PATH=%LOCAL_BROWSERS%
playwright install chromium

if %errorlevel% neq 0 (
    echo ======================================================
    echo  Browser installation failed. Trying global install...
    echo ======================================================
    playwright install chromium
)

echo.
echo ===============================================================
echo   ✅ Setup Complete!
echo ===============================================================
echo.
echo   You can now use "RUN BOT.bat" to start the bot anytime.
echo   The setup is complete and you won't need to run this again.
echo.
pause