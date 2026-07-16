@echo off
REM Builds PostgresExport.exe as a single portable file with the icon
REM embedded both as the exe's own icon and as a bundled resource
REM (so the app window itself shows it too).
REM
REM Run this on a Windows machine with Python installed.
REM Requires: pg_export_gui.py and icon.ico in this same folder.

echo Installing build dependencies...
pip install --upgrade pyinstaller psycopg2-binary

echo.
echo Building PostgresExport.exe ...
pyinstaller --onefile --windowed --name PostgresExport ^
    --icon=icon.ico ^
    --add-data "icon.ico;." ^
    main.py

echo.
echo Done. Find it at: dist\PostgresExport.exe
echo Copy that file, together with icon.ico, install.ps1, install.bat,
echo uninstall.ps1 and uninstall.bat into one folder - that folder is
echo now portable to any Windows 10/11 machine.
pause
