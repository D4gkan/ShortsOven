@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM Guarantee the window stays open no matter what happens below
REM (crash, unexpected exit, etc.), not just when we reach the
REM final `pause`. On first run (no marker arg) we relaunch this
REM same script inside a `cmd /k` shell -- /k keeps the console
REM alive after the batch finishes or dies, unlike /c. The marker
REM arg stops this from relaunching itself forever.
REM ============================================================
if /I not "%~1"=="__running__" (
    cmd /k "%~f0" __running__
    exit /b
)

title AI Reddit Story Video Generator

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
echo %C_TITLE%%C_BOLD%              AI REDDIT STORY VIDEO GENERATOR%C_RESET%
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

call venv\Scripts\activate.bat
echo %C_OK%  [OK]%C_RESET% Virtual environment ready.
echo.

REM ============================================================
REM Step 2/3 - Voice selection (asked ONCE for the whole batch)
REM VOICE_GENDER is exported for the rest of this cmd session, and
REM every main.py invocation in the batch loop below inherits it --
REM tts_engine.py already reads this env var itself, so nothing
REM else needs to pass the voice choice around explicitly.
REM ============================================================
echo %C_STEP%[2/3] Choose a narration voice (used for the entire batch)%C_RESET%
echo   %C_DIM%[M]%C_RESET% Male
echo   %C_DIM%[F]%C_RESET% Female
echo.
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
if exist "!DONEFLAG!" del /q "!DONEFLAG!" >nul 2>&1

start "" /b cmd /c "python main.py --image "!CURRENT_IMAGE!" > "!LOGFILE!" 2>&1 & echo %%errorlevel%% > "!DONEFLAG!""

<nul set /p "=     Working"
:BATCH_WAITLOOP
if not exist "!DONEFLAG!" (
    <nul set /p "=."
    timeout /t 1 /nobreak >nul
    goto BATCH_WAITLOOP
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

if "!EXIT_NONZERO!"=="1" (
    echo %C_WARN%  [WARNING] python exited with code !EXITCODE! after the video was%C_RESET%
    echo %C_WARN%  already saved -- likely a harmless shutdown crash, not a real failure.%C_RESET%
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
REM Same cache-clear mechanism as before -- asks Python for the
REM resolved cache path so this keeps working even if cache_dir is
REM ever changed in config.json.
for /f "usebackq delims=" %%c in (`python -c "from src.config import load_config; c=load_config(); print(c.abspath(c.cache_dir))"`) do set "CACHE_DIR=%%c"
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