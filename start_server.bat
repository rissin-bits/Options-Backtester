@echo off
title Options Backtester Server
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║          NSE Options Backtester - Local Server              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: Get the directory where this script lives
cd /d "%~dp0"

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Check if uvicorn is available
python -c "import uvicorn" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing backend dependencies...
    pip install -r backend\requirements.txt
)

:: Get local IP for display
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do (
        set LOCAL_IP=%%b
    )
)

echo.
echo  Starting server...
echo.
echo  ┌─────────────────────────────────────────────────────────┐
echo  │  Local:    http://localhost:8000                        │
echo  │  Network:  http://%LOCAL_IP%:8000                  │
echo  │                                                         │
echo  │  Press Ctrl+C to stop the server                        │
echo  └─────────────────────────────────────────────────────────┘
echo.

:: Start the FastAPI server
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000

pause
