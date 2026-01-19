@echo off
REM PostgreSQL Export Tool - Uninstaller Launcher
REM This batch file will launch the PowerShell uninstaller with administrator privileges

echo =========================================
echo PostgreSQL Export Tool - Uninstaller
echo =========================================
echo.
echo This will remove the PostgreSQL Export tool from your system
echo and remove it from your Windows 11 context menu.
echo.
echo Administrator privileges are required.
echo.
pause

REM Run PowerShell script as Administrator
powershell -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0uninstall.ps1\"'"

echo.
echo Uninstallation script launched. Please check the Administrator PowerShell window.
echo.
pause
