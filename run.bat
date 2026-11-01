@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ===================================
echo  Tool tao video Threads - Khoi dong
echo ===================================

REM --- Python 3.11+ ---
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Can Python 3.11 tro len. Tai tai https://www.python.org/downloads/
    echo       Khi cai nho tick "Add Python to PATH".
    pause
    exit /b 1
)

REM --- FFmpeg ---
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Chua tim thay FFmpeg.
    echo       Cach nhanh: mo PowerShell va chay:  winget install Gyan.FFmpeg
    echo       Sau do DONG cua so nay, mo lai va chay run.bat lan nua.
    pause
    exit /b 1
)

REM --- Moi truong ao + thu vien ---
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Tao moi truong ao .venv ...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [INFO] Kiem tra thu vien (lan dau mat vai phut)...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [LOI] Cai thu vien that bai. Kiem tra ket noi mang roi chay lai.
    pause
    exit /b 1
)

REM --- Trinh duyet Chromium cho tinh nang lay bai tu link Threads (chi cai 1 lan) ---
if not exist ".venv\.chromium_ok" (
    echo [INFO] Cai trinh duyet Chromium cho Playwright...
    python -m playwright install chromium && echo ok> ".venv\.chromium_ok"
)

echo.
echo [OK] Mo trinh duyet tai http://localhost:8000   (Ctrl+C de dung)
echo.
start "" /min cmd /c "timeout /t 4 >nul & start http://localhost:8000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
