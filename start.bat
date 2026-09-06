@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul

title SHORTS OVEN

REM ============================================================
REM ANSI color setup. Native in cmd.exe on Windows 10 1607+;
REM on anything older these codes just print as harmless plain
REM text, so this never breaks compatibility -- only appearance.
REM ============================================================
for /F %%a in ('echo prompt $E^|cmd') do set "ESC=%%a"
set "C_TITLE=%ESC%[96m"
set "C_OK=%ESC%[92m"
set "C_WARN=%ESC%[93m"
set "C_ERR=%ESC%[91m"
set "C_PROMPT=%ESC%[95m"
set "C_STEP=%ESC%[94m"
set "C_TAG=%ESC%[96m"
set "C_DIM=%ESC%[90m"
set "C_BOLD=%ESC%[1m"
set "C_RESET=%ESC%[0m"

set "LINE==============================================================="

cls
echo %C_TITLE%%LINE%%C_RESET%
echo %C_TITLE%%C_BOLD%                       SHORTS OVEN%C_RESET%
echo %C_TITLE%%LINE%%C_RESET%
echo.

REM ============================================================
REM Step 1/3 - Environment check
REM ============================================================
echo %C_STEP%[1/3] Checking environment...%C_RESET%

if not exist venv (
    echo %C_ERR%  [ERROR]%C_RESET% Virtual environment not found. Run setup.bat first.
    echo.
    pause
    exit /b 1
)

set "VENV_PYTHON=%CD%\venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo %C_ERR%  [ERROR]%C_RESET% Virtual environment interpreter not found. Run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo %C_OK%  [OK]%C_RESET% Virtual environment ready.
echo   Using: "%VENV_PYTHON%"
echo.

REM ============================================================
REM Step 2/3 - Voice selection (asked ONCE for the whole batch)
REM VOICE_GENDER is exported for the rest of this cmd session, and
REM every main.py invocation in the batch loop below inherits it --
REM tts_engine.py already reads this env var itself, so nothing
REM else needs to pass the voice choice around explicitly.
REM ============================================================
:VOICE_SELECTION
echo %C_STEP%[2/3] Choose a narration voice (used for the entire batch)%C_RESET%
echo   %C_DIM%[M]%C_RESET% Male
echo   %C_DIM%[F]%C_RESET% Female
echo.
set "VOICE_CHOICE="
choice /c MF /n /m "  Enter your choice (M/F): "
if errorlevel 2 (
    set "VOICE_GENDER=female"
    set "VOICE_LABEL=Female"
) else (
    set "VOICE_GENDER=male"
    set "VOICE_LABEL=Male"
)

echo.
echo %C_OK%  [OK]%C_RESET% Voice set to: %C_PROMPT%%VOICE_LABEL%%C_RESET% (applies to every video in this batch)
echo.

REM ============================================================
REM Hashtag pool -- IDENTICAL to the original pool/algorithm, just
REM loaded once here and drawn from fresh (via :BuildHashtags)
REM for every individual video instead of once for the whole run.
REM ============================================================
set /a TAGCOUNT=0
for %%T in (
    #foryou #storytime #youtubeshorts #shortvideo #reddit #funny
    #viralvideo #illustration #tattoo #artting #pov #procreate
    #drawing #whydidntmyexcomeback #digitalart #pourtoi #Shorts
    #YouTubeShorts #Viral #Storytelling #Stories #Relaxation
    #Relaxing #stressrelief #story #funnyvideo #shorts #trending
    #viral #fyp #asmr #relatable #ytshorts #foryoupage #explore
    #recommended #shortsfeed #foreignreaction #shortsvira
    #funnyculture #StressRelief #stories #cooking
) do (
    set /a TAGCOUNT+=1
    set "TAG[!TAGCOUNT!]=%%~T"
)
set "PICKMAX=6"
if !TAGCOUNT! LSS 6 set "PICKMAX=!TAGCOUNT!"

REM ============================================================
REM Step 3/3 - Batch generation
REM Rescans assets\images before every video (folder is the
REM source of truth, never cached), runs the existing pipeline
REM unchanged via main.py --image <file>, clears cache after
REM every attempt, and on success renames the output to the
REM randomized hashtag string and deletes the source image. Any
REM failure stops the whole batch and keeps the failed image.
REM ============================================================
echo %C_STEP%[3/3] Batch: generating videos for every image in assets\images ...%C_RESET%
echo %C_DIM%  This can take a while depending on how many images are queued.%C_RESET%
echo.

if not exist logs mkdir logs

set "IMAGES_DIR=assets\images"
set /a VIDEO_INDEX=0

:BATCH_LOOP

REM Rescan every time -- same image formats asset_manager.py
REM already supports (IMAGE_EXTS = png/jpg/jpeg/webp).
set "CURRENT_IMAGE="
for %%F in ("%IMAGES_DIR%\*.png" "%IMAGES_DIR%\*.jpg" "%IMAGES_DIR%\*.jpeg" "%IMAGES_DIR%\*.webp") do (
    if not defined CURRENT_IMAGE if exist "%%~F" set "CURRENT_IMAGE=%%~F"
)

if not defined CURRENT_IMAGE goto BATCH_SUCCESS

set /a VIDEO_INDEX+=1
echo %C_STEP%  -- Image !VIDEO_INDEX!: !CURRENT_IMAGE!%C_RESET%

set "LOGFILE=logs\run_%RANDOM%_!VIDEO_INDEX!.log"
set "DONEFLAG=%TEMP%\redditgen_done_%RANDOM%_!VIDEO_INDEX!.flag"
set "PIDFILE=%TEMP%\redditgen_pid_%RANDOM%_!VIDEO_INDEX!.txt"
set "ERRORLOG=%TEMP%\redditgen_error_%RANDOM%_!VIDEO_INDEX!.log"
set "ELAPSEDFILE=%TEMP%\redditgen_elapsed_%RANDOM%_!VIDEO_INDEX!.txt"
if exist "!DONEFLAG!" del /q "!DONEFLAG!" >nul 2>&1
if exist "!PIDFILE!" del /q "!PIDFILE!" >nul 2>&1
if exist "!ERRORLOG!" del /q "!ERRORLOG!" >nul 2>&1
if exist "!ELAPSEDFILE!" del /q "!ELAPSEDFILE!" >nul 2>&1

start "" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%VENV_PYTHON%' -ArgumentList @('main.py','--image','!CURRENT_IMAGE!') -WindowStyle Hidden -RedirectStandardOutput '%LOGFILE%' -RedirectStandardError '%ERRORLOG%' -PassThru; Set-Content -LiteralPath '%PIDFILE%' -Value $p.Id -Encoding ascii; $p.WaitForExit(); if (Test-Path -LiteralPath '%ERRORLOG%') { Get-Content -LiteralPath '%ERRORLOG%' | Add-Content -LiteralPath '%LOGFILE%' }; Set-Content -LiteralPath '%DONEFLAG%' -Value $p.ExitCode -Encoding ascii"

set /a ELAPSED=0
set "PROCESS_ID="
:BATCH_WAITLOOP
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\batch_status.ps1" -PidFile "!PIDFILE!" -DoneFlag "!DONEFLAG!" -ElapsedFile "!ELAPSEDFILE!" 2>nul
if errorlevel 1 (
    echo %C_WARN%Work interrupted%C_RESET%
    if exist "!PIDFILE!" del /q "!PIDFILE!" >nul 2>&1
    if exist "!ERRORLOG!" del /q "!ERRORLOG!" >nul 2>&1
    if exist "!DONEFLAG!" del /q "!DONEFLAG!" >nul 2>&1
    if exist "!ELAPSEDFILE!" del /q "!ELAPSEDFILE!" >nul 2>&1
    exit /b 130
)
echo.

set /p EXITCODE=<"!DONEFLAG!"
del /q "!DONEFLAG!" >nul 2>&1

REM Same tolerance as before: PaddleOCR/PyTorch can crash during
REM interpreter shutdown *after* the video was already saved, which
REM still exits python non-zero -- "Video ready:" in the log is the
REM real signal, not the process exit code.
set "VIDEO_OK=0"
findstr /C:"Video ready:" "!LOGFILE!" >nul 2>&1
if not errorlevel 1 set "VIDEO_OK=1"

set "EXIT_NONZERO=0"
if not "!EXITCODE!"=="0" set "EXIT_NONZERO=1"

set "HARDFAIL=0"
if "!EXIT_NONZERO!"=="1" if "!VIDEO_OK!"=="0" set "HARDFAIL=1"

REM Cache is cleared after EVERY attempt -- success or failure --
REM before deciding what happens next.
call :ClearCache

if "!HARDFAIL!"=="1" (
    echo %C_ERR%%LINE%%C_RESET%
    echo %C_ERR% [ERROR] Video generation failed for: !CURRENT_IMAGE!%C_RESET%
    echo %C_ERR% Full log saved to: %CD%\!LOGFILE!%C_RESET%
    echo %C_ERR% The source image was kept so it can be inspected/retried.%C_RESET%
    echo %C_ERR% Batch stopped -- no further images will be processed.%C_RESET%
    echo %C_ERR%%LINE%%C_RESET%
    echo.
    echo %C_DIM%Last lines of the log:%C_RESET%
    powershell -NoProfile -Command "Get-Content -Tail 15 '!LOGFILE!'" 2>nul
    echo.
    pause
    exit /b 1
)

REM Pull the exact output path main.py reported, and confirm it's
REM really on disk before treating this as a success (per spec: never
REM delete the source image on an unconfirmed/assumed success).
set "VIDEOLINE="
for /f "delims=" %%L in ('findstr /C:"Video ready:" "!LOGFILE!"') do set "VIDEOLINE=%%L"
set "OUTVIDEO=!VIDEOLINE:*Video ready: =!"

if not exist "!OUTVIDEO!" (
    echo %C_ERR%%LINE%%C_RESET%
    echo %C_ERR% [ERROR] main.py reported success but no output file was found%C_RESET%
    echo %C_ERR% at: !OUTVIDEO!%C_RESET%
    echo %C_ERR% The source image was kept. Batch stopped.%C_RESET%
    echo %C_ERR%%LINE%%C_RESET%
    pause
    exit /b 1
)

set "COMPLETED_SECONDS=0"
if exist "!ELAPSEDFILE!" set /p COMPLETED_SECONDS=<"!ELAPSEDFILE!"
set /a COMPLETED_MINUTES=COMPLETED_SECONDS/60
set /a COMPLETED_REMAINDER=COMPLETED_SECONDS%%60
if !COMPLETED_REMAINDER! LSS 10 (set "DISPLAY_COMPLETED_SECONDS=0!COMPLETED_REMAINDER!") else (set "DISPLAY_COMPLETED_SECONDS=!COMPLETED_REMAINDER!")
echo %C_PROMPT%     Work completed (!COMPLETED_MINUTES!m !DISPLAY_COMPLETED_SECONDS!s)%C_RESET%
if exist "!ELAPSEDFILE!" del /q "!ELAPSEDFILE!" >nul 2>&1

call :BuildHashtags

set "OUTDIR="
for %%P in ("!OUTVIDEO!") do set "OUTDIR=%%~dpP"

REM Filename is ONLY the hashtag string (no image name/index/
REM timestamp) -- with collision-safe numbering only in the rare
REM case two random draws land on the exact same combination, so a
REM previously completed video is never silently overwritten.
set "TARGETPATH=!OUTDIR!!TAGLINE!.mp4"
set /a COLLISION_N=1
:BATCH_COLLISION_CHECK
if exist "!TARGETPATH!" (
    set /a COLLISION_N+=1
    set "TARGETPATH=!OUTDIR!!TAGLINE! (!COLLISION_N!).mp4"
    goto BATCH_COLLISION_CHECK
)

move /y "!OUTVIDEO!" "!TARGETPATH!" >nul
echo %C_OK%     [OK] Saved: !TARGETPATH!%C_RESET%

del /q "!CURRENT_IMAGE!" >nul 2>&1
echo %C_OK%     [OK] Removed source image: !CURRENT_IMAGE!%C_RESET%
echo.

goto BATCH_LOOP

:BATCH_SUCCESS
echo %C_OK%%LINE%%C_RESET%
echo %C_OK%%C_BOLD%  Batch creation successful%C_RESET%
echo %C_OK%%LINE%%C_RESET%
echo.
pause
exit /b 0

REM ============================================================
REM Subroutines
REM ============================================================

:ClearCache
REM config.json uses a project-relative cache directory, so avoid
REM invoking a nested quoted Python command from cmd.exe here.
set "CACHE_DIR=%CD%\cache"
if defined CACHE_DIR (
    if exist "!CACHE_DIR!" (
        del /q "!CACHE_DIR!\*" >nul 2>&1
        for /d %%d in ("!CACHE_DIR!\*") do rd /s /q "%%d" >nul 2>&1
    )
)
exit /b

:BuildHashtags
REM Draws PICKMAX unique random indices from the hashtag pool set up
REM above (identical algorithm to the original one-shot version),
REM leaving TAGLINE holding the space-joined result with no leading
REM space.
set "PICKED= "
set /a N=0
:BuildHashtags_pick
if !N! GEQ !PICKMAX! goto BuildHashtags_done
set /a R=(!RANDOM! %% !TAGCOUNT!) + 1
echo !PICKED!| findstr /C:" !R! " >nul
if not errorlevel 1 goto BuildHashtags_pick
set "PICKED=!PICKED!!R! "
set /a N+=1
goto BuildHashtags_pick
:BuildHashtags_done
set "TAGLINE="
for %%I in (!PICKED!) do set "TAGLINE=!TAGLINE! !TAG[%%I]!"
set "TAGLINE=!TAGLINE:~1!"
exit /b