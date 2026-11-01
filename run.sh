#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "==================================="
echo " Tool tạo video Threads - Khởi động"
echo "==================================="

PY=python3
command -v python3.11 >/dev/null 2>&1 && PY=python3.11
if ! $PY -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
    echo "[LỖI] Cần Python 3.11 trở lên."
    echo "  macOS:  brew install python@3.11"
    echo "  Ubuntu: sudo apt install python3.11 python3.11-venv"
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "[LỖI] Chưa cài FFmpeg."
    echo "  macOS:  brew install ffmpeg"
    echo "  Ubuntu: sudo apt install ffmpeg"
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[INFO] Tạo môi trường ảo .venv ..."
    $PY -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[INFO] Kiểm tra thư viện (lần đầu mất vài phút)..."
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

if [ ! -f ".venv/.chromium_ok" ]; then
    echo "[INFO] Cài trình duyệt Chromium cho Playwright..."
    if python -m playwright install chromium; then
        touch .venv/.chromium_ok
    fi
    if [ "$(uname)" = "Linux" ]; then
        echo "[GỢI Ý] Nếu lấy link Threads báo thiếu thư viện hệ thống, chạy: sudo .venv/bin/playwright install-deps chromium"
    fi
fi

echo ""
echo "[OK] Mở trình duyệt tại http://localhost:8000   (Ctrl+C để dừng)"
echo ""
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
