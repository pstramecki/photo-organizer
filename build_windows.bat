@echo off
REM =========================================================================
REM  Build PhotoOrganizer.exe -- one-time setup, run this once, then use the
REM  .exe on any Windows machine without needing Python at all.
REM
REM  Prereq: Python 3.8+ installed (https://www.python.org/downloads/).
REM          During install tick "Add python.exe to PATH".
REM
REM  Result: dist\PhotoOrganizer.exe  (single file, no console window)
REM =========================================================================

setlocal
cd /d "%~dp0"

echo.
echo === Checking Python ===
where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not on PATH.
  echo Install it from https://www.python.org/downloads/ and re-run this script.
  echo During install, tick "Add python.exe to PATH".
  pause
  exit /b 1
)
python --version

echo.
echo === Creating build virtual environment ===
if not exist ".buildenv" (
  python -m venv .buildenv || goto :fail
)
call .buildenv\Scripts\activate.bat || goto :fail

echo.
echo === Installing build dependencies ===
python -m pip install --upgrade pip       || goto :fail
python -m pip install pyinstaller Pillow  || goto :fail

echo.
echo === Building single-file executable ===
REM --onefile   : one .exe, unpacks to a temp dir at runtime
REM --windowed  : no console window pops up alongside the GUI
REM --name      : output name
REM --noconfirm : overwrite previous build without asking
pyinstaller ^
  --onefile ^
  --windowed ^
  --noconfirm ^
  --name PhotoOrganizer ^
  run.py || goto :fail

echo.
echo =========================================================================
echo  BUILD OK.
echo  Your executable is:  %CD%\dist\PhotoOrganizer.exe
echo  Copy it anywhere. No Python needed to run it.
echo =========================================================================
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. See messages above.
pause
exit /b 1
