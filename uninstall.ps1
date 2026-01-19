# PostgreSQL Export Tool - Context Menu Uninstaller
# Run this script as Administrator

param(
    [string]$InstallPath = "$env:ProgramFiles\PostgresExport"
)

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Export Tool - Uninstaller" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Please right-click on PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

Write-Host "Removing context menu entries from Windows Registry..." -ForegroundColor Yellow

# Import uninstall registry file
$regFile = Join-Path $PSScriptRoot "uninstall_context_menu.reg"
if (Test-Path $regFile) {
    try {
        Start-Process -FilePath "reg.exe" -ArgumentList "import `"$regFile`"" -Wait -NoNewWindow
        Write-Host "Context menu entries removed." -ForegroundColor Green
    } catch {
        Write-Host "WARNING: Failed to remove some registry entries!" -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Yellow
    }
} else {
    Write-Host "WARNING: uninstall_context_menu.reg not found!" -ForegroundColor Yellow
}

# Remove installation directory
if (Test-Path $InstallPath) {
    Write-Host "Removing installation directory: $InstallPath" -ForegroundColor Yellow
    try {
        Remove-Item -Path $InstallPath -Recurse -Force
        Write-Host "Installation directory removed." -ForegroundColor Green
    } catch {
        Write-Host "WARNING: Failed to remove installation directory!" -ForegroundColor Yellow
        Write-Host "You may need to remove it manually: $InstallPath" -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Yellow
    }
} else {
    Write-Host "Installation directory not found (already removed)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Uninstallation completed!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""

Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
