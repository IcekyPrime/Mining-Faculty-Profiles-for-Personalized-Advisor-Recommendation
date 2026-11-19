@echo off
setlocal EnableExtensions
title Advisor Finder - One Click Run
cd /d "%~dp0"
rem Make sure the Windows tools resolve even when PATH is minimal.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

rem ------------------------------------------------------------------
rem  One-click launcher for the Advisor Finder (Flask + SQLite).
rem  Usage:
rem      run.bat              start on port 8765 and open the browser
rem      run.bat 8766         start on a custom port
rem      run.bat --no-browser start without opening the browser
rem  This file is ASCII-only on purpose: no encoding issues on any console.
rem ------------------------------------------------------------------

set "PORT=8765"
set "NOBROWSER="
for %%A in (%*) do (
  if /i "%%~A"=="--no-browser" set "NOBROWSER=1"
  set "MAYBE=%%~A"
  for /f "delims=0123456789" %%i in ("%%~A") do set "MAYBE="
  if defined MAYBE set "PORT=%%~A"
)

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "URL=http://127.0.0.1:%PORT%/"
set "DEPS=flask,numpy,pandas,sklearn,networkx,mlxtend,jieba,pypinyin"

echo.
echo ================================================================
echo   Advisor Finder - one click launcher
echo   Project : %~dp0
echo   Port    : %PORT%
echo ================================================================
echo.

echo [1/3] Checking Python runtime...
if not exist "%PY%" goto :create_venv
echo   found %PY%
"%PY%" -c "import %DEPS%" >nul 2>nul
if errorlevel 1 (
  echo   dependencies missing, installing from requirements.txt...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :pip_failed
)
goto :check_data

:create_venv
echo   .venv not found, creating a virtual environment...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%VENV%"
) else (
  python -m venv "%VENV%"
)
if errorlevel 1 goto :no_python
echo   installing dependencies, this may take a few minutes...
"%PY%" -m pip install --upgrade pip >nul 2>nul
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed

:check_data
echo [2/3] Checking database and port...
if not exist "data\db\mentor.db" (
  echo   WARNING: data\db\mentor.db was not found.
  echo            Search and insights pages will fail until the database exists.
)
"%PY%" -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); sys.exit(0 if s.connect_ex(('127.0.0.1',%PORT%)) else 1)" >nul 2>nul
if errorlevel 1 (
  echo   WARNING: port %PORT% is already in use.
  echo            Close that process, or start with: run.bat 8766
)

echo [3/3] Starting server: %URL%
echo   Press Ctrl+C to stop the server.
echo.
set "MENTOR_PORT=%PORT%"
set "PYTHONUTF8=1"
if defined NOBROWSER goto :start_server
start "" /b "%PY%" "%~dp0scripts\open_browser.py" "%URL%"

:start_server
"%PY%" -m app.app
set "CODE=%ERRORLEVEL%"
echo.
echo Server stopped, exit code %CODE%.
if not defined NOBROWSER pause
exit /b %CODE%

:no_python
echo.
echo ERROR: Python 3 was not found.
echo Install Python 3.10+ from https://www.python.org/downloads/
echo and enable "Add python.exe to PATH" during setup, then run this file again.
echo.
pause
exit /b 1

:pip_failed
echo.
echo ERROR: pip install failed. Check the network, then run manually:
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1
