"""
assets.py — Đảm bảo thư mục và tài nguyên mặc định tồn tại khi khởi động.

- Font Be Vietnam Pro (app/fonts/): nếu thiếu thì thử tải từ Google Fonts (giấy phép OFL).
- Âm "bụp" (library/sfx/pop.mp3): nếu thiếu thì tự tổng hợp.
"""
from __future__ import annotations

import logging
import math
import shutil
import urllib.request
import wave

import numpy as np

from app.config import CACHE_DIR, FONTS_DIR, LIBRARY_DIR, MEDIA_KINDS, PROJECTS_DIR, media_dir

log = logging.getLogger("assets")

FONT_URLS = {
    "BeVietnamPro-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bevietnampro/BeVietnamPro-Regular.ttf",
    "BeVietnamPro-SemiBold.ttf": "https://github.com/google/fonts/raw/main/ofl/bevietnampro/BeVietnamPro-SemiBold.ttf",
}


def ensure_dirs() -> None:
    for d in (LIBRARY_DIR / "music", LIBRARY_DIR / "sfx", PROJECTS_DIR, CACHE_DIR / "tts", FONTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for kind in MEDIA_KINDS:  # nen_video/, meme/, video_da_duyet/
        media_dir(kind)
    memes_json = LIBRARY_DIR / "memes.json"
    if not memes_json.exists():
        memes_json.write_text("[]", encoding="utf-8")
    _migrate_old_folders()


def _migrate_old_folders() -> None:
    """Bản cũ để nền/meme trong library/backgrounds và library/memes → chuyển sang thư mục mới."""
    import os
    if os.environ.get("TTV_LIBRARY_DIR"):
        return
    for old_name, kind in (("backgrounds", "background"), ("memes", "meme")):
        old = LIBRARY_DIR / old_name
        if not old.is_dir():
            continue
        new = media_dir(kind)
        for f in old.iterdir():
            if f.is_file() and not f.name.startswith(".") and not (new / f.name).exists():
                shutil.move(str(f), str(new / f.name))
                log.info("Đã chuyển %s → %s", f, new)
        if not any(p for p in old.iterdir() if not p.name.startswith(".")):
            shutil.rmtree(old, ignore_errors=True)


def ensure_fonts(timeout: float = 15) -> None:
    for name, url in FONT_URLS.items():
        dest = FONTS_DIR / name
        if dest.exists() and dest.stat().st_size > 10_000:
            continue
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = r.read()
            if len(data) > 10_000:
                dest.write_bytes(data)
                log.info("Đã tải font %s", name)
        except Exception as exc:  # không có mạng → dùng font hệ thống
            log.warning("Không tải được font %s (%s); dùng font hệ thống thay thế.", name, exc)


def synth_pop(path, sr: int = 44100) -> None:
    """Tổng hợp tiếng 'bụp' ngắn: sóng sin quét tần số giảm dần + đường bao tắt nhanh."""
    dur = 0.16
    t = np.arange(int(sr * dur)) / sr
    freq = 900 * np.exp(-t * 28) + 180
    phase = 2 * math.pi * np.cumsum(freq) / sr
    env = np.minimum(1.0, t / 0.004) * np.exp(-t * 32)
    sig = 0.85 * np.sin(phase) * env
    sig += 0.15 * np.random.default_rng(1).standard_normal(len(t)) * np.exp(-t * 120)
    sig = np.clip(sig, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((sig * 32767).astype(np.int16).tobytes())


def ensure_pop_sfx() -> None:
    sfx_dir = LIBRARY_DIR / "sfx"
    if any((sfx_dir / n).exists() for n in ("pop.mp3", "pop.wav")):
        return
    wav = sfx_dir / "pop.wav"
    synth_pop(wav)
    if shutil.which("ffmpeg"):
        from app.utils import run_ffmpeg
        try:
            run_ffmpeg(["-i", str(wav), "-c:a", "libmp3lame", "-q:a", "2", str(sfx_dir / "pop.mp3")])
            wav.unlink(missing_ok=True)
        except RuntimeError:
            pass


def ensure_all() -> None:
    ensure_dirs()
    ensure_pop_sfx()
    ensure_fonts()
