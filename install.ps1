# PostgreSQL Export Tool - Installer
#
# Copies PostgresExport.exe into Program Files and registers it in the
# Explorer right-click context menu, both for a folder itself and for
# the empty background inside a folder.
#
# Portable: copy this whole folder (install.ps1, install.bat,
# PostgresExport.exe, icon.ico) to any Windows 10/11 machine and run
# install.bat. This script self-elevates - no need to manually
# "Run as Administrator".

param(
    [string]$InstallPath = "$env:ProgramFiles\PostgresExport"
)

$ErrorActionPreference = "Stop"

# --- Self-elevate if not already Administrator ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting administrator privileges..." -ForegroundColor Yellow
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs
    exit
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " PostgreSQL Export Tool - Installer" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Install directory: $InstallPath" -ForegroundColor Green
Write-Host ""

# --- Locate source files (must sit next to this script) ---
$sourceExe = Join-Path $PSScriptRoot "PostgresExport.exe"
$sourceIcon = Join-Path $PSScriptRoot "icon.ico"

if (-not (Test-Path $sourceExe)) {
    Write-Host "ERROR: PostgresExport.exe not found next to this script." -ForegroundColor Red
    Write-Host "Build it first with build_exe.bat on a machine with Python," -ForegroundColor Yellow
    Write-Host "then copy PostgresExport.exe here and re-run this installer." -ForegroundColor Yellow
    pause
    exit 1
}

# --- Copy files into place ---
New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
Copy-Item $sourceExe -Destination $InstallPath -Force
if (Test-Path $sourceIcon) {
    Copy-Item $sourceIcon -Destination $InstallPath -Force
}

$exeDest = Join-Path $InstallPath "PostgresExport.exe"
Write-Host "Installed to: $exeDest" -ForegroundColor Green
Write-Host ""

# --- Register context menu entries (HKLM = visible to all users) ---
function Set-ContextMenuEntry {
    param([string]$BasePath, [string]$ArgPlaceholder)

    $keyPath = "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\$BasePath\shell\PGExportTool"
    $cmdPath = "$keyPath\command"

    New-Item -Path $keyPath -Force | Out-Null
    Set-ItemProperty -Path $keyPath -Name "(default)" -Value "Export PostgreSQL Database Here"
    Set-ItemProperty -Path $keyPath -Name "Icon" -Value "`"$exeDest`",0"

    New-Item -Path $cmdPath -Force | Out-Null
    Set-ItemProperty -Path $cmdPath -Name "(default)" -Value "`"$exeDest`" `"$ArgPlaceholder`""
}

Write-Host "Registering context menu entries..." -ForegroundColor Yellow
Set-ContextMenuEntry -BasePath "Directory" -ArgPlaceholder "%1"
Set-ContextMenuEntry -BasePath "Directory\Background" -ArgPlaceholder "%V"

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host " Installation complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Right-click any folder, or right-click inside a folder," -ForegroundColor Cyan
Write-Host "and choose 'Export PostgreSQL Database Here'." -ForegroundColor Cyan
Write-Host ""
pause
