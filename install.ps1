# PostgreSQL Export Tool - Context Menu Installer
# Run this script as Administrator

param(
    [string]$InstallPath = "$env:ProgramFiles\PostgresExport"
)

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "PostgreSQL Export Tool - Installer" -ForegroundColor Cyan
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

Write-Host "Installation directory: $InstallPath" -ForegroundColor Green
Write-Host ""

# Create installation directory
if (-not (Test-Path $InstallPath)) {
    Write-Host "Creating installation directory..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}

# Copy executable to installation directory
$exePath = Join-Path $PSScriptRoot "PostgresExport.exe"
if (Test-Path $exePath) {
    Write-Host "Copying PostgresExport.exe to installation directory..." -ForegroundColor Yellow
    Copy-Item $exePath -Destination $InstallPath -Force
} else {
    Write-Host "ERROR: PostgresExport.exe not found in current directory!" -ForegroundColor Red
    Write-Host "Please ensure PostgresExport.exe is in the same folder as this script." -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

# Create registry file with actual installation path
Write-Host "Creating registry configuration..." -ForegroundColor Yellow
$regTemplate = Get-Content (Join-Path $PSScriptRoot "install_context_menu.reg.template") -Raw
$regContent = $regTemplate -replace '%INSTALL_PATH%', $InstallPath.Replace('\', '\\')
$regFile = Join-Path $env:TEMP "install_context_menu.reg"
$regContent | Out-File -FilePath $regFile -Encoding ASCII

# Import registry settings
Write-Host "Adding context menu entries to Windows Registry..." -ForegroundColor Yellow
try {
    Start-Process -FilePath "reg.exe" -ArgumentList "import `"$regFile`"" -Wait -NoNewWindow
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host "Installation completed successfully!" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "You can now right-click on any folder or drive and select" -ForegroundColor Cyan
    Write-Host "'Export PostgreSQL Database Here' to export a database to that location." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Installation location: $InstallPath" -ForegroundColor White
    Write-Host ""
} catch {
    Write-Host "ERROR: Failed to import registry settings!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
}

# Cleanup
Remove-Item $regFile -Force -ErrorAction SilentlyContinue

Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
