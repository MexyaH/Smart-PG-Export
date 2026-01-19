
@echo off
REM PostgreSQL Export Tool - Installer Launcher
REM This batch file will launch the PowerShell installer with administrator privileges

echo =========================================
echo PostgreSQL Export Tool - Installer
echo =========================================
echo.
echo This will install the PostgreSQL Export tool and add it to your
echo Windows 11 context menu (right-click menu).
echo.
echo Administrator privileges are required.
echo.
pause

REM Run PowerShell script as Administrator
powershell -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0install.ps1\"'"

echo.
echo Installation script launched. Please check the Administrator PowerShell window.
echo.
pause
