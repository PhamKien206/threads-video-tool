"""
media.py — Ba thư mục người dùng: video nền, meme, video đã duyệt.

Đường dẫn lấy từ cấu hình (app.config.media_dir). Có ảnh thu nhỏ (cache/thumbs) để giao diện xem trước.
"""
from __future__ import annotations

import re

import hashlib
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from app.config import CACHE_DIR, media_dir
from app.utils import ffprobe_duration, safe_filename, unique_path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
THUMB_DIR = CACHE_DIR / "thumbs"

_info_cache: dict[tuple[str, float], dict] = {}
_lock = threading.Lock()


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def safe_media_path(kind: str, file: str) -> Path:
    """Đường dẫn file trong thư mục *kind*; chặn '../' ra ngoài thư mục."""
    base = media_dir(kind).resolve()
    p = (base / Path(file).name).resolve()
    if p.parent != base:
        raise ValueError("Tên file không hợp lệ.")
    return p


def has_audio(path: str | Path) -> bool:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                            "stream=index", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=20)
        return bool(r.stdout.strip())
    except Exception:
        return False


def media_info(path: Path) -> dict:
    """Thời lượng + có tiếng hay không (cache theo thời điểm sửa file)."""
    key = (str(path), path.stat().st_mtime)
    with _lock:
        if key in _info_cache:
            return _info_cache[key]
    info = {"duration": None, "audio": False}
    if path.suffix.lower() in AUDIO_EXTS:
        try:
            info["duration"] = round(ffprobe_duration(path), 1)
        except RuntimeError:
            pass
        info["audio"] = True
    elif is_video(path):
        try:
            info["duration"] = round(ffprobe_duration(path), 1)
        except RuntimeError:
            pass
        info["audio"] = has_audio(path)
    with _lock:
        _info_cache[key] = info
    return info


def list_files(kind: str, exts: set[str]) -> list[dict]:
    d = media_dir(kind)
    out = []
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("."):
            typ = "video" if is_video(p) else ("audio" if p.suffix.lower() in AUDIO_EXTS else "image")
            out.append({"file": p.name, "type": typ,
                        "size_mb": round(p.stat().st_size / 1_048_576, 1), **media_info(p)})
    return out


def list_backgrounds() -> list[dict]:
    return list_files("background", VIDEO_EXTS | (IMAGE_EXTS - {".gif"}))


def list_music() -> list[dict]:
    """Nhạc nền trong thư mục nhạc (mặc định ./nhac_nen). Thêm cả nhạc cũ ở library/music nếu có."""
    return list_files("music", AUDIO_EXTS)


def list_approved() -> list[dict]:
    items = list_files("approved", VIDEO_EXTS)
    d = media_dir("approved")
    for it in items:
        txt = d / (Path(it["file"]).stem + ".txt")
        it["caption_file"] = txt.name if txt.exists() else None
        it["mtime"] = int((d / it["file"]).stat().st_mtime)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def add_file(kind: str, filename: str, fileobj, exts: set[str]) -> str:
    """Lưu file upload vào thư mục *kind* (ghi theo luồng, không đọc cả file vào RAM)."""
    ext = Path(filename or "").suffix.lower()
    if ext not in exts:
        raise ValueError(f"Định dạng {ext or '(không rõ)'} không hỗ trợ. Hỗ trợ: {', '.join(sorted(exts))}")
    dest = unique_path(media_dir(kind), safe_filename(filename, kind))
    with open(dest, "wb") as out:
        shutil.copyfileobj(fileobj, out, length=4 * 1024 * 1024)
    return dest.name


def delete_file(kind: str, file: str) -> None:
    p = safe_media_path(kind, file)
    if not p.exists():
        raise KeyError("Không tìm thấy file.")
    p.unlink()
    if kind == "approved":
        p.with_suffix(".txt").unlink(missing_ok=True)


def thumbnail(kind: str, file: str) -> Path:
    """Ảnh JPG thu nhỏ (rộng 320 px) cho ảnh/GIF/video, cache trong cache/thumbs."""
    src = safe_media_path(kind, file)
    if not src.exists():
        raise KeyError("Không tìm thấy file.")
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime}".encode("utf-8")).hexdigest()[:20]
    out = THUMB_DIR / f"{key}.jpg"
    if out.exists():
        return out
    if is_video(src):
        dur = media_info(src).get("duration") or 0
        at = min(3.0, dur / 3) if dur else 0
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=320:-2", str(out)], capture_output=True, timeout=60)
        if not out.exists():
            raise RuntimeError("Không tạo được ảnh xem trước cho video.")
    else:
        from PIL import Image
        with Image.open(src) as im:
            im.seek(0)
            im = im.convert("RGBA")
            im.thumbnail((320, 320))
            bg = Image.new("RGB", im.size, (39, 39, 42))
            bg.paste(im, mask=im.split()[3])
            bg.save(out, "JPEG", quality=85)
    return out


def video_frame_png(path: Path, out: Path) -> Path:
    """Lấy 1 khung hình giữa video (cho AI xem khi gắn nhãn meme video)."""
    dur = media_info(path).get("duration") or 0
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(path),
                    "-frames:v", "1", str(out)], capture_output=True, timeout=60)
    if not out.exists():
        raise RuntimeError("Không lấy được khung hình từ video meme.")
    return out


def open_folder(kind: str) -> str:
    """Mở thư mục trong trình quản lý file của máy (Explorer/Finder). Trả về đường dẫn."""
    d = media_dir(kind)
    try:
        if sys.platform == "win32":
            os.startfile(str(d))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(d)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return str(d)


def approved_name(title: str, stamp: str, part: Optional[int]) -> str:
    """Tên file video đã duyệt: '<Chủ đề có dấu> - <ngày giờ>[ - Part N].mp4'.

    Giữ tiếng Việt có dấu cho dễ đọc; bỏ ký tự Windows cấm (<>:"/\\|?*) và ký tự lạ.
    """
    import unicodedata
    t = unicodedata.normalize("NFC", str(title or ""))
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", t)
    t = re.sub(r"[^\w\s-]", " ", t)
    t = re.sub(r"[_\s]+", " ", t).strip(" .-")[:80].rstrip(" .-") or "Video"
    return f"{t} - {stamp}" + (f" - Part {part}" if part else "") + ".mp4"
