# PostgreSQL Export Tool - Uninstaller
#
# Removes the context menu entries and the installed program files.
# Portable: works the same on any machine where install.ps1 was used.

param(
    [string]$InstallPath = "$env:ProgramFiles\PostgresExport"
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting administrator privileges..." -ForegroundColor Yellow
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs
    exit
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " PostgreSQL Export Tool - Uninstaller" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Removing context menu entries..." -ForegroundColor Yellow
Remove-Item -Path "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Directory\shell\PGExportTool" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Directory\Background\shell\PGExportTool" -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $InstallPath) {
    Write-Host "Removing installed files from $InstallPath..." -ForegroundColor Yellow
    Remove-Item -Path $InstallPath -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host " Uninstall complete." -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
pause
