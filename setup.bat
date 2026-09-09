@echo off
setlocal
cd /d "%~dp0"
echo ShortsOven - Setup
set "PYTHONUTF8=1"

where ffmpeg >nul 2>&1
if errorlevel 1 goto NO_FFMPEG
where ffprobe >nul 2>&1
if errorlevel 1 goto NO_FFMPEG

if exist "venv\Scripts\python.exe" goto CHECK_PYTHON
py -3.11 -m venv venv
if errorlevel 1 (
    echo [ERROR] Install Python 3.11 with the Windows Python launcher, then retry.
    goto FAILED
)
:CHECK_PYTHON
set "VENV_PYTHON=%CD%\venv\Scripts\python.exe"
"%VENV_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,11) else 1)"
if errorlevel 1 (
    echo [ERROR] This setup supports Python 3.11. Rename the old venv folder and retry.
    goto FAILED
)
"%VENV_PYTHON%" scripts\check_ollama.py --pull
if errorlevel 1 goto FAILED
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto FAILED
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto FAILED
"%VENV_PYTHON%" -m pip check
if errorlevel 1 goto FAILED
"%VENV_PYTHON%" scripts\download_models.py
if errorlevel 1 goto FAILED

echo Setup complete. Add media to assets and run start.bat.
pause
exit /b 0
:NO_FFMPEG
echo [ERROR] Install FFmpeg and add its bin folder to PATH. Both ffmpeg and ffprobe are required.
:FAILED
echo [ERROR] Setup did not finish. Resolve the error above and retry.
pause
exit /b 1
