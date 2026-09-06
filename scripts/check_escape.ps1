Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ShortsOvenKeyState
{
    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int virtualKey);
}
'@

if (([ShortsOvenKeyState]::GetAsyncKeyState(0x1B) -band 0x8000) -ne 0) {
    exit 1
}

exit 0
