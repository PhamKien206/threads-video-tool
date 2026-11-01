"""
memes.py — Thư viện meme: thư mục meme (mặc định ./meme, đổi được trong Cài đặt) + library/memes.json.

Mỗi meme: {"file", "name", "tags", "description", "type": "image" | "video"}.
Chép tay file vào thư mục meme cũng được — lần mở thư viện sau sẽ tự nhận.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from PIL import Image

from app.config import CACHE_DIR, LIBRARY_DIR, media_dir
from app.llm.base import LLMBase
from app.pipeline.media import VIDEO_EXTS, is_video, safe_media_path, video_frame_png
from app.pipeline.ocr import load_prompt
from app.utils import read_json, safe_filename, unique_path, write_json

MEMES_JSON = LIBRARY_DIR / "memes.json"
IMAGE_EXTS = {".png", ".gif", ".webp", ".jpg", ".jpeg"}
ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS
_lock = threading.Lock()


def memes_dir() -> Path:
    return media_dir("meme")


def _resolve(file: str) -> Path:
    return safe_media_path("meme", file)


def list_memes() -> list[dict]:
    """Danh sách meme; tự thêm vào json những file được chép tay vào thư mục meme."""
    MEMES_DIR = memes_dir()
    with _lock:
        data = [m for m in (read_json(MEMES_JSON, []) or []) if isinstance(m, dict) and m.get("file")]
        known = {m["file"] for m in data}
        changed = False
        for f in sorted(MEMES_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in ALLOWED_EXTS and f.name not in known:
                data.append({"file": f.name, "name": f.stem, "tags": [], "description": ""})
                changed = True
        alive = [m for m in data if (MEMES_DIR / m["file"]).exists()]
        if changed or len(alive) != len(data):
            write_json(MEMES_JSON, alive)
        for m in alive:
            m["type"] = "video" if is_video(m["file"]) else "image"
            m.setdefault("name", Path(m["file"]).stem)
            m.setdefault("tags", [])
            m.setdefault("description", "")
        return alive


def _save(data: list[dict]) -> None:
    with _lock:
        write_json(MEMES_JSON, data)


def add_meme(filename: str, content: bytes) -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Định dạng {ext or '(không rõ)'} không hỗ trợ. Dùng PNG, GIF, WebP hoặc video MP4/WebM/MOV.")
    dest = unique_path(memes_dir(), safe_filename(filename, "meme"))
    dest.write_bytes(content)
    if ext in IMAGE_EXTS:
        try:
            with Image.open(dest) as im:
                im.verify()
        except Exception:
            dest.unlink(missing_ok=True)
            raise ValueError(f"File '{filename}' không phải ảnh hợp lệ.")
    data = list_memes()
    entry = next((m for m in data if m["file"] == dest.name), None)
    if entry is None:
        entry = {"file": dest.name, "name": Path(filename).stem, "tags": [], "description": ""}
        data.append(entry)
    else:
        entry["name"] = Path(filename).stem
    _save(data)
    return entry


def update_meme(file: str, fields: dict) -> dict:
    data = list_memes()
    for m in data:
        if m["file"] == file:
            if "name" in fields and fields["name"] is not None:
                m["name"] = str(fields["name"]).strip()[:80]
            if "description" in fields and fields["description"] is not None:
                m["description"] = str(fields["description"]).strip()[:300]
            if "tags" in fields and fields["tags"] is not None:
                tags = fields["tags"]
                if isinstance(tags, str):
                    tags = tags.split(",")
                m["tags"] = [t.strip().lower() for t in tags if str(t).strip()][:12]
            _save(data)
            return m
    raise KeyError("Không tìm thấy meme.")


def delete_meme(file: str) -> None:
    data = list_memes()
    remaining = [m for m in data if m["file"] != file]
    if len(remaining) == len(data):
        raise KeyError("Không tìm thấy meme.")
    _resolve(file).unlink(missing_ok=True)
    _save(remaining)


def _tag_validator(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return "phải là object JSON"
    if not isinstance(data.get("tags"), list) or not data["tags"]:
        return '"tags" phải là danh sách không rỗng'
    if not str(data.get("name", "")).strip():
        return 'thiếu "name"'
    return None


async def tag_meme(file: str, llm: LLMBase) -> dict:
    """AI gắn nhãn (prompt B4)."""
    path = _resolve(file)
    if not path.exists():
        raise KeyError("Không tìm thấy meme.")
    image = path
    if is_video(path):  # AI chỉ xem ảnh → lấy 1 khung hình giữa video
        (CACHE_DIR / "frames").mkdir(parents=True, exist_ok=True)
        image = video_frame_png(path, CACHE_DIR / "frames" / f"{path.stem}.png")
    prompt = load_prompt("meme_tagger.md")
    if is_video(path):
        prompt += "\n\n(Đây là một khung hình lấy từ meme dạng VIDEO ngắn.)"
    res = await llm.complete_json(prompt, image_path=str(image), validator=_tag_validator)
    return update_meme(file, {
        "name": res.get("name"), "description": res.get("description"),
        "tags": [str(t) for t in res.get("tags", []) if not str(t).startswith("vd:")],
    })


def remove_white_background(file: str, tolerance: int = 18) -> dict:
    """Xóa nền trắng: flood fill từ 4 góc rồi chuyển vùng đó thành trong suốt. Lưu thành PNG."""
    path = _resolve(file)
    if not path.exists():
        raise KeyError("Không tìm thấy meme.")
    if path.suffix.lower() == ".gif" or is_video(path):
        raise ValueError("Chỉ xóa nền được cho ảnh tĩnh (PNG/JPG/WebP), không áp dụng cho GIF hoặc video.")
    with Image.open(path) as im:
        rgba = np.array(im.convert("RGBA"))
    rgb = np.ascontiguousarray(rgba[:, :, :3][:, :, ::-1])  # BGR cho OpenCV
    h, w = rgb.shape[:2]
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    lo = up = (tolerance,) * 3
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        b, g, r = rgb[y, x]
        if min(int(b), int(g), int(r)) >= 200 and mask[y + 1, x + 1] == 0:  # chỉ fill nếu góc là màu sáng
            cv2.floodFill(rgb, mask, (x, y), (0, 0, 0), lo, up, flags)
    region = mask[1:-1, 1:-1] > 0
    if not region.any():
        raise ValueError("Không thấy nền trắng ở các góc ảnh để xóa.")
    # làm mềm mép một chút
    soft = cv2.GaussianBlur(region.astype(np.float32), (3, 3), 0)
    rgba[:, :, 3] = (rgba[:, :, 3].astype(np.float32) * (1 - soft)).astype(np.uint8)

    out = path.with_suffix(".png")
    if out != path:
        out = unique_path(memes_dir(), out.name)
    Image.fromarray(rgba, "RGBA").save(out, "PNG")
    data = list_memes()
    for m in data:
        if m["file"] == file:
            if out != path:
                path.unlink(missing_ok=True)
                m["file"] = out.name
            _save([x for x in data if (memes_dir() / x["file"]).exists()])
            return m
    raise KeyError("Không tìm thấy meme.")
