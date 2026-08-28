@echo off
setlocal
cd /d "%~dp0"

set "DIST_EXE=dist\erp_offline.exe"
set "SETUP_OUTPUT=dist\ERP_Setup_v1.0.exe"
set "ISCC_PATH="

for %%I in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if exist "%%~I" set "ISCC_PATH=%%~I"

REM Build executable using PyInstaller
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m pip install -q --upgrade pyinstaller
pyinstaller --noconfirm --onefile --name erp_offline --hidden-import aiosqlite --hidden-import gspread --hidden-import google.auth --hidden-import google.oauth2.service_account --add-data "app\static;static" app\main.py
pyinstaller --noconfirm --onefile --name erp_offline --hidden-import aiosqlite --add-data "app\static;static" app\main.py
if %ERRORLEVEL% NEQ 0 (
    echo Build failed with errorlevel %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

if not exist "%DIST_EXE%" (
    echo Missing executable: %DIST_EXE%
    pause
    exit /b 1
)

if "%ISCC_PATH%"=="" (
    echo Inno Setup not found. Install Inno Setup 6 and rerun this script.
    pause
    exit /b 1
)

"%ISCC_PATH%" /O"%~dp0dist" /F"ERP_Setup_v1.0" "%~dp0installer.iss"
if %ERRORLEVEL% NEQ 0 (
    echo Inno Setup compilation failed with errorlevel %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo Build finished. Output: %SETUP_OUTPUT%
pause
