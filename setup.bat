@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  AI Reddit Story Video Generator - Setup
echo ============================================
echo.

REM ============================================================
REM Detect and select Python version
REM PaddleOCR supports Python 3.9 - 3.13
REM ============================================================

set PYTHON_CMD=python
set PYTHON_VERSION=

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i

echo Checking Python version: %PYTHON_VERSION%

for /f "tokens=2" %%i in ('python --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%a in ('echo %%i') do (
        set PYTHON_MAJOR=%%a
        set PYTHON_MINOR=%%b
    )
)

if "!PYTHON_MAJOR!"=="3" (
    if !PYTHON_MINOR! gtr 13 (
        echo [WARNING] Python 3.!PYTHON_MINOR! detected, but PaddleOCR only supports 3.9-3.13.
        echo Attempting to fall back to Python 3.13, 3.12, 3.11...

        set FOUND_ALT=0

        for %%v in (3.13 3.12 3.11 3.10) do (
            py -%%v --version >nul 2>&1
            if !errorlevel! equ 0 (
                echo [OK] Found Python %%v via Windows Python launcher.
                set PYTHON_CMD=py -%%v
                set FOUND_ALT=1
                goto PYTHON_OK
            )
        )

        if !FOUND_ALT! equ 0 (
            echo.
            echo [ERROR] No supported Python version was found.
            echo Please install Python 3.11, 3.12 or 3.13.
            pause
            exit /b 1
        )
    )
)

:PYTHON_OK

echo.
echo [OK] Python version OK:
%PYTHON_CMD% --version

echo.

REM ============================================================
REM Verify FFmpeg
REM ============================================================

ffmpeg -version >nul 2>&1

if errorlevel 1 (
    echo [ERROR] ffmpeg was not found on PATH.
    echo Download FFmpeg and add its "bin" folder to PATH.
    pause
    exit /b 1
)

echo [OK] ffmpeg found.

echo.

REM ============================================================
REM Create virtual environment
REM ============================================================

if not exist venv (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv venv

    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo.

REM ============================================================
REM Upgrade pip
REM ============================================================

echo Upgrading pip...

python -m pip install --upgrade pip

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to upgrade pip.
    pause
    exit /b 1
)

echo.

REM ============================================================
REM Install requirements
REM ============================================================

echo Installing Python requirements (this can take a while)...

python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [WARNING] First installation attempt failed.
    echo Retrying without cache...
    echo.

    python -m pip install --no-cache-dir -r requirements.txt
)

if errorlevel 1 (
    echo.
    echo ============================================================
    echo ERROR
    echo ============================================================
    echo.
    echo Failed to install one or more Python packages.
    echo.
    echo This is commonly caused by:
    echo.
    echo  - Windows Defender Application Control (WDAC)
    echo  - Device Guard
    echo  - AppLocker
    echo  - Corporate security policies
    echo.
    echo If you are using a personal PC, try:
    echo.
    echo   1. Running setup.bat as Administrator
    echo   2. Disabling Smart App Control temporarily
    echo   3. Running:
    echo.
    echo      python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.

REM ============================================================
REM Download AI models
REM ============================================================

echo Downloading offline OCR / TTS / alignment models...

python scripts\download_models.py

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to download AI models.
    pause
    exit /b 1
)

echo.

echo ============================================
echo  Setup complete!
echo ============================================
echo.
echo 1. Drop images into assets\images
echo 2. Drop backgrounds into assets\backgrounds
echo 3. Drop music into assets\music
echo 4. Run start.bat
echo.

pause