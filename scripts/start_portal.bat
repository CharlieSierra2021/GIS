@echo off
rem One-command launcher for the Property Intel demo portal.
rem Usage: scripts\start_portal.bat [--port 8012] [--no-open]
setlocal
cd /d "%~dp0.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=.venv\bin\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
    echo Dependencies not found. Run:
    echo   %PY% -m pip install -e ".[dev]"
    exit /b 1
)

"%PY%" scripts\dev_seed.py %*
