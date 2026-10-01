@echo off
REM Double-click to open your Second Brain. First run sets everything up (about a minute).
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || goto :nopython
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Second Brain ^(about a minute^)...
  %PY% -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -e ".[excel]" || goto :fail
  ".venv\Scripts\python.exe" -m pip install --quiet extract-msg >nul 2>nul || echo ^(Optional Outlook .msg support could not be installed - everything else works.^)
)
echo Starting Second Brain. Your browser will open at http://localhost:8787
echo Keep this window open while you use it; close it to stop.
".venv\Scripts\python.exe" -m secondbrain ui
pause
exit /b 0
:nopython
echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then double-click this file again.
pause
exit /b 1
:fail
echo Setup failed - see the messages above. Delete the .venv folder and try again.
pause
exit /b 1
