param(
    [Parameter(Mandatory = $true)]
    [string]$PidFile,
    [Parameter(Mandatory = $true)]
    [string]$DoneFlag,
    [Parameter(Mandatory = $true)]
    [string]$ElapsedFile,
    [string]$LogFile
)

$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$lastShownSecond = -1
$stage = 'Starting'
$lastPrintedStage = ''
$interactive = -not [Console]::IsOutputRedirected
$canReadKeys = -not [Console]::IsInputRedirected
$displayAvailable = $true
$esc = [char]27
$spinner = @('|', '/', '-', '\')
$oldCursorVisible = $true
if ($interactive) {
    try { $oldCursorVisible = [Console]::CursorVisible; [Console]::CursorVisible = $false } catch {}
}

try {
    while (-not (Test-Path -LiteralPath $DoneFlag)) {
        $elapsedSeconds = [int][math]::Floor($stopwatch.Elapsed.TotalSeconds)
        if ($elapsedSeconds -ne $lastShownSecond) {
            $clock = '{0:00}:{1:00}' -f [math]::Floor($elapsedSeconds / 60), ($elapsedSeconds % 60)
            if ($LogFile -and (Test-Path -LiteralPath $LogFile)) {
                $recent = Get-Content -LiteralPath $LogFile -Tail 12 -ErrorAction SilentlyContinue |
                    Where-Object { $_ -match '^\[INFO\]' } | Select-Object -Last 1
                switch -Regex ($recent) {
                    'Encoding: (\d+)%' { $stage = "Encoding $($Matches[1])%"; break }
                    'Rendering conversation' { $stage = 'Rendering video'; break }
                    'Building conversation' { $stage = 'Arranging conversation'; break }
                    'Preparing background|Background clip' { $stage = 'Preparing background'; break }
                    'Analyzing speech|forced-alignment' { $stage = 'Synchronizing speech'; break }
                    'Generating narration|Qwen3-TTS|Using offline' { $stage = 'Generating voice'; break }
                    'Choosing story tone|Story tone' { $stage = 'Choosing story tone'; break }
                    'OCR|Detected|Line |username|Loading image' { $stage = 'Reading screenshot'; break }
                    'Video ready:|Done. Output' { $stage = 'Finishing'; break }
                }
            }
            $status = "    $($spinner[$elapsedSeconds % 4])  $stage  /  $clock  /  Esc to stop"
            if ($displayAvailable) {
                try {
                    if ($interactive) {
                        # Never pad beyond the window width: doing so wraps and creates
                        # a new blank row on every tick in narrow terminals.
                        $width = [Console]::WindowWidth
                        if ($width -le 1) { $width = 80 }
                        $limit = [math]::Max(1, $width - 1)
                        if ($status.Length -gt $limit) {
                            $status = $status.Substring(0, [math]::Max(0, $limit - 3)) + '...'
                            if ($status.Length -gt $limit) { $status = $status.Substring(0, $limit) }
                        }
                        [Console]::Write("`r${esc}[2K${esc}[96m$status${esc}[0m")
                        $Host.UI.RawUI.WindowTitle = "ShortsOven - $stage - $clock"
                    } elseif ($stage -ne $lastPrintedStage) {
                        Write-Output "    $stage / $clock"
                        $lastPrintedStage = $stage
                    }
                } catch {
                    $displayAvailable = $false
                    $interactive = $false
                    $canReadKeys = $false
                    if ($LogFile) {
                        Add-Content -LiteralPath $LogFile -Value "[WARNING] Progress display disconnected; generation continues: $_" -ErrorAction SilentlyContinue
                    }
                }
            }
            $lastShownSecond = $elapsedSeconds
        }

        # Read this console's input queue, never the desktop-wide keyboard state.
        $stopRequested = $false
        if ($canReadKeys) {
            try {
                while ([Console]::KeyAvailable) {
                    if ([Console]::ReadKey($true).Key -eq [ConsoleKey]::Escape) {
                        $stopRequested = $true
                    }
                }
            } catch {
                $canReadKeys = $false
            }
        }
        if ($stopRequested) {
            if ($LogFile) { Add-Content -LiteralPath $LogFile -Value "[DIAGNOSTIC] Stop requested: Escape pressed in ShortsOven console." }
            if (Test-Path -LiteralPath $PidFile) {
                $processId = (Get-Content -LiteralPath $PidFile -Raw).Trim()
                if ($processId -match '^\d+$') {
                    & taskkill.exe /PID $processId /T /F > $null 2>&1
                }
            }
            exit 1
        }
        Start-Sleep -Milliseconds 100
    }
    $completedSeconds = [math]::Floor($stopwatch.Elapsed.TotalSeconds)
    Set-Content -LiteralPath $ElapsedFile -Value $completedSeconds -Encoding ascii -ErrorAction Stop
} catch {
    # Progress reporting must never terminate an otherwise healthy generation.
    if ($LogFile) {
        Add-Content -LiteralPath $LogFile -Value "[WARNING] Status monitor switched to silent waiting; generation continues: $_" -ErrorAction SilentlyContinue
    }
    $interactive = $false
    while (-not (Test-Path -LiteralPath $DoneFlag)) {
        Start-Sleep -Milliseconds 100
    }
    try {
        Set-Content -LiteralPath $ElapsedFile -Value ([math]::Floor($stopwatch.Elapsed.TotalSeconds)) -Encoding ascii -ErrorAction Stop
    } catch {
        exit 2
    }
} finally {
    if ($interactive) {
        try {
            [Console]::Write("`r${esc}[2K")
            [Console]::CursorVisible = $oldCursorVisible
            $Host.UI.RawUI.WindowTitle = 'ShortsOven'
        } catch {}
    }
}
exit 0
