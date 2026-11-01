"""
utils.py — Hàm tiện ích dùng chung.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"Không tìm thấy '{name}'. Hãy cài FFmpeg (gồm ffmpeg và ffprobe) và thêm vào PATH "
            "(Windows: winget install Gyan.FFmpeg rồi mở lại cửa sổ dòng lệnh)."
        )
    return path


def ffprobe_duration(path: str | Path) -> float:
    """Thời lượng (giây) của file media."""
    require_binary("ffprobe")
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Không đọc được thời lượng của {Path(path).name}: {r.stderr.strip()[:200]}")


def run_ffmpeg(args: list[str], timeout: int = 600) -> None:
    require_binary("ffmpeg")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg lỗi: {r.stderr.strip()[-600:]}")


def imread(path: str | Path):
    """cv2.imread không đọc được đường dẫn có dấu tiếng Việt trên Windows → dùng imdecode."""
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path: str | Path, img) -> None:
    import cv2
    ext = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise RuntimeError(f"Không ghi được ảnh {path}")
    buf.tofile(str(path))


def safe_filename(name: str, default: str = "file") -> str:
    """Bỏ dấu, ký tự lạ; giữ phần mở rộng."""
    name = Path(name or default).name
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    stem = unicodedata.normalize("NFKD", stem).replace("đ", "d").replace("Đ", "D")
    stem = stem.encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower() or default
    ext = re.sub(r"[^a-z0-9.]", "", ext)[:6]
    return f"{stem[:60]}{ext}"


def unique_path(directory: Path, filename: str) -> Path:
    p = directory / filename
    stem, ext = p.stem, p.suffix
    i = 2
    while p.exists():
        p = directory / f"{stem}_{i}{ext}"
        i += 1
    return p


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
