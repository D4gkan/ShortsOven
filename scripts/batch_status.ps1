param(
    [Parameter(Mandatory = $true)]
    [string]$PidFile,
    [Parameter(Mandatory = $true)]
    [string]$DoneFlag,
    [Parameter(Mandatory = $true)]
    [string]$ElapsedFile,
    [string]$LogFile
)

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ShortsOvenKeyState
{
    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int virtualKey);
}
'@

$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$lastShownSecond = -1
$stage = 'Starting'
$lastPrintedStage = ''
$interactive = -not [Console]::IsOutputRedirected
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
            $lastShownSecond = $elapsedSeconds
        }

        if (([ShortsOvenKeyState]::GetAsyncKeyState(0x1B) -band 0x8000) -ne 0) {
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
    Set-Content -LiteralPath $ElapsedFile -Value $completedSeconds -Encoding ascii
} finally {
    if ($interactive) {
        [Console]::Write("`r${esc}[2K")
        try { [Console]::CursorVisible = $oldCursorVisible } catch {}
        $Host.UI.RawUI.WindowTitle = 'ShortsOven'
    }
}
exit 0
