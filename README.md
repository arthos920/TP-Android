if ($env:OS -eq 'Windows_NT' -and $env:CI_JOB_ID) {
    if (-not ('CheckActorsConsoleStop' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class CheckActorsConsoleStop
{
    private delegate bool ControlHandler(uint signal);
    private static readonly ControlHandler Handler = Handle;

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetConsoleCtrlHandler(
        ControlHandler handler,
        [MarshalAs(UnmanagedType.Bool)] bool add);

    public static void Install()
    {
        if (!SetConsoleCtrlHandler(Handler, true))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    private static bool Handle(uint signal)
    {
        if (signal == 1) // CTRL_BREAK_EVENT
        {
            Environment.Exit(1);
            return true;
        }

        return false;
    }
}
'@
    }

    [CheckActorsConsoleStop]::Install()
}



if ($robotExitCode -eq -1073741510) {
    throw 'Robot interrompu par Windows : arrêt des retries.'
}

