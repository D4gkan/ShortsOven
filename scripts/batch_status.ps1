param(
    [Parameter(Mandatory = $true)]
    [string]$PidFile,
    [Parameter(Mandatory = $true)]
    [string]$DoneFlag,
    [Parameter(Mandatory = $true)]
    [string]$ElapsedFile
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

while (-not (Test-Path -LiteralPath $DoneFlag)) {
    $elapsedSeconds = [math]::Floor($stopwatch.Elapsed.TotalSeconds)
    if ($elapsedSeconds -ne $lastShownSecond) {
        $minutes = [math]::Floor($elapsedSeconds / 60)
        $seconds = $elapsedSeconds % 60
        $displaySeconds = $seconds.ToString('00')
        $status = "     Working (${minutes}m ${displaySeconds}s - Esc to interrupt)"
        $Host.UI.RawUI.WindowTitle = "ShortsOven - $($status.Trim())"
        [Console]::Write([char]13)
        [Console]::Write((' ' * 90))
        [Console]::Write([char]13)
        [Console]::Write($status)
        $lastShownSecond = $elapsedSeconds
    }

    if (([ShortsOvenKeyState]::GetAsyncKeyState(0x1B) -band 0x8000) -ne 0) {
        if (Test-Path -LiteralPath $PidFile) {
            $processId = (Get-Content -LiteralPath $PidFile -Raw).Trim()
            if ($processId -match '^\d+$') {
                Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
            }
        }
        exit 1
    }

    Start-Sleep -Milliseconds 100
}

$completedSeconds = [math]::Floor($stopwatch.Elapsed.TotalSeconds)
Set-Content -LiteralPath $ElapsedFile -Value $completedSeconds -Encoding ascii
exit 0
