param(
    [Parameter(Mandatory = $true)]
    [string]$LogDirectory
)

$ErrorActionPreference = "Stop"

$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $appRoot "..")).Path
$frontendRoot = Join-Path $appRoot "frontend"
$resolvedLogDirectory = [System.IO.Path]::GetFullPath($LogDirectory)

New-Item -ItemType Directory -Path $resolvedLogDirectory -Force | Out-Null

$backendOutputLog = Join-Path $resolvedLogDirectory "backend-console.log"
$backendErrorLog = Join-Path $resolvedLogDirectory "backend-console-error.log"
$frontendOutputLog = Join-Path $resolvedLogDirectory "frontend.log"
$frontendErrorLog = Join-Path $resolvedLogDirectory "frontend-error.log"

$backendProcess = $null
$frontendProcess = $null
$scriptExitCode = 0

# PowerShell's ReadKey/TreatControlCAsInput behavior is inconsistent when this
# script is launched by cmd.exe from run.bat. A native console handler receives
# Ctrl+C, Ctrl+Break, and console-close events reliably without aborting the
# PowerShell pipeline before the finally block can clean up both process trees.
Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class AppConsoleStopSignal
{
    private enum CtrlType : uint
    {
        CtrlC = 0,
        CtrlBreak = 1,
        CtrlClose = 2
    }

    private delegate bool HandlerRoutine(CtrlType ctrlType);
    private static HandlerRoutine handler;
    public static volatile bool Requested;

    [DllImport("Kernel32", SetLastError = true)]
    private static extern bool SetConsoleCtrlHandler(
        HandlerRoutine handlerRoutine,
        bool add
    );

    public static void Install()
    {
        Requested = false;
        handler = Handle;
        if (!SetConsoleCtrlHandler(handler, true))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public static void Uninstall()
    {
        if (handler != null)
        {
            SetConsoleCtrlHandler(handler, false);
            handler = null;
        }
    }

    private static bool Handle(CtrlType ctrlType)
    {
        if (ctrlType == CtrlType.CtrlC ||
            ctrlType == CtrlType.CtrlBreak ||
            ctrlType == CtrlType.CtrlClose)
        {
            Requested = true;
            return true;
        }
        return false;
    }
}
"@

function Assert-PortAvailable {
    param([int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $listener) {
        throw "Port $Port is already in use by PID $($listener.OwningProcess). Stop that process before starting the app."
    }
}

function Stop-ProcessTree {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$Name
    )

    if ($null -eq $Process) {
        return
    }

    try {
        $Process.Refresh()
        if ($Process.HasExited) {
            return
        }

        Write-Host "[INFO] Stopping $Name process tree (PID $($Process.Id))..."
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
        Wait-Process -Id $Process.Id -Timeout 10 -ErrorAction SilentlyContinue
    }
    catch {
        Write-Warning "Could not completely stop ${Name}: $($_.Exception.Message)"
    }
}

try {
    [AppConsoleStopSignal]::Install()
    Assert-PortAvailable -Port 8000
    Assert-PortAvailable -Port 5173

    $poetry = (Get-Command poetry -ErrorAction Stop).Source
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source

    Write-Host "[INFO] Launching backend server..."
    $backendProcess = Start-Process `
        -FilePath $poetry `
        -ArgumentList @(
            "run", "python", "-m", "v2.run_daemon",
            "v2/funds/example.yaml", "--interval", "manual",
            "--host", "127.0.0.1", "--port", "8000", "--log-dir", "logs"
        ) `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $backendOutputLog `
        -RedirectStandardError $backendErrorLog `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 3
    $backendProcess.Refresh()
    if ($backendProcess.HasExited) {
        throw "Backend exited during startup. Check $backendErrorLog"
    }

    Write-Host "[INFO] Launching frontend development server..."
    $frontendProcess = Start-Process `
        -FilePath $npm `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $frontendRoot `
        -RedirectStandardOutput $frontendOutputLog `
        -RedirectStandardError $frontendErrorLog `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 5
    $frontendProcess.Refresh()
    if ($frontendProcess.HasExited) {
        throw "Frontend exited during startup. Check $frontendErrorLog"
    }

    Start-Process "http://localhost:5173"

    Write-Host ""
    Write-Host "[SUCCESS] AI Hedge Fund web application is now running"
    Write-Host "[INFO] Frontend: http://localhost:5173"
    Write-Host "[INFO] Backend:  http://localhost:8000"
    Write-Host "[INFO] Docs:     http://localhost:8000/docs"
    Write-Host "[INFO] Logs:     $resolvedLogDirectory"
    Write-Host ""
    Write-Host "[INFO] Press Ctrl+C to stop both services..."

    while ($true) {
        if ([AppConsoleStopSignal]::Requested) {
            Write-Host ""
            Write-Host "[INFO] Stop requested"
            break
        }

        $backendProcess.Refresh()
        $frontendProcess.Refresh()
        if ($backendProcess.HasExited) {
            throw "Backend stopped unexpectedly. Check $backendErrorLog"
        }
        if ($frontendProcess.HasExited) {
            throw "Frontend stopped unexpectedly. Check $frontendErrorLog"
        }
        Start-Sleep -Milliseconds 100
    }
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    $scriptExitCode = 1
}
finally {
    Stop-ProcessTree -Process $frontendProcess -Name "frontend"
    Stop-ProcessTree -Process $backendProcess -Name "backend"
    [AppConsoleStopSignal]::Uninstall()
    if ($null -ne $backendProcess -or $null -ne $frontendProcess) {
        Write-Host "[SUCCESS] Services stopped. Goodbye"
    }
}

exit $scriptExitCode
