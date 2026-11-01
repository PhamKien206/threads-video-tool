"""
tts — Tạo giọng đọc cho từng câu, có cache.

Mỗi câu → 1 file WAV (44.1 kHz mono) trong cache/tts/<hash>.wav, hash = (engine, text, voice, speed).
Thời lượng đo từ số mẫu âm của WAV (chính xác hơn đọc metadata mp3).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
import wave
from pathlib import Path
from typing import Callable, Optional

from app.config import CACHE_DIR
from app.pipeline.tts.base import TTSBase, TTSError
from app.utils import run_ffmpeg

log = logging.getLogger("ttv.tts")

SAMPLE_RATE = 44100
TTS_CACHE = CACHE_DIR / "tts"


def get_tts(cfg: dict) -> TTSBase:
    engine = (cfg.get("tts_engine") or "edge").lower()
    if engine == "vieneu":
        from app.pipeline.tts.vieneu import VieNeuTTS
        return VieNeuTTS()
    from app.pipeline.tts.edge import EdgeTTS
    return EdgeTTS()


def list_voices() -> list[dict]:
    from app.pipeline.tts.edge import VOICES
    return [{"engine": "edge", **v} for v in VOICES] + [
        {"engine": "vieneu", "id": "default", "name": "VieNeu mặc định (offline)"}]


def cache_key(engine: str, text: str, voice: str, speed: str) -> str:
    return hashlib.sha256(f"{engine}|{voice}|{speed}|{text}".encode("utf-8")).hexdigest()[:32]


def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


async def synthesize_cached(text: str, cfg: dict) -> tuple[str, float]:
    """Tạo (hoặc lấy từ cache) WAV cho một câu. Trả về (đường dẫn wav, thời lượng giây)."""
    from app.pipeline.textnorm import clean_for_tts, has_speakable
    text = clean_for_tts(text)
    if not has_speakable(text):
        # Câu chỉ toàn ký hiệu/emoji → thay bằng 0,4 giây im lặng thay vì báo lỗi
        TTS_CACHE.mkdir(parents=True, exist_ok=True)
        silent = TTS_CACHE / "silence_0.4.wav"
        if not silent.exists():
            await asyncio.to_thread(run_ffmpeg, ["-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono",
                                                 "-t", "0.4", "-c:a", "pcm_s16le", str(silent)])
        return str(silent), wav_duration(silent)
    engine = get_tts(cfg)
    voice = cfg.get("tts_voice") or "vi-VN-HoaiMyNeural"
    speed = cfg.get("tts_speed") or "+0%"
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    wav = TTS_CACHE / f"{cache_key(engine.name, text, voice, speed)}.wav"
    if wav.exists() and wav.stat().st_size > 44:
        return str(wav), wav_duration(wav)

    tmp_raw = TTS_CACHE / f"tmp_{uuid.uuid4().hex}{engine.output_ext}"
    tmp_wav = TTS_CACHE / f"tmp_{uuid.uuid4().hex}.wav"
    try:
        await engine.synthesize(text, str(tmp_raw), voice, speed)
        await asyncio.to_thread(
            run_ffmpeg, ["-i", str(tmp_raw), "-ac", "1", "-ar", str(SAMPLE_RATE),
                         "-c:a", "pcm_s16le", str(tmp_wav)])
        os.replace(tmp_wav, wav)
    finally:
        for p in (tmp_raw, tmp_wav):
            if p.exists():
                p.unlink(missing_ok=True)
    return str(wav), wav_duration(wav)


def _alt_voice(cfg: dict) -> Optional[dict]:
    """Giọng Edge tiếng Việt còn lại (Microsoft đôi khi lỗi riêng một giọng, giọng kia vẫn chạy)."""
    if (cfg.get("tts_engine") or "edge").lower() != "edge":
        return None
    from app.pipeline.tts.edge import VOICES
    cur = cfg.get("tts_voice") or "vi-VN-HoaiMyNeural"
    return next((v for v in VOICES if v["id"] != cur), None)


async def _synthesize_all(texts: dict[str, str], cfg: dict,
                          on_progress: Optional[Callable[[int, int], None]]) -> dict[str, tuple[str, float]]:
    sem = asyncio.Semaphore(max(1, getattr(get_tts(cfg), "concurrency", 2)))
    done = 0
    total = len(texts)
    results: dict[str, tuple[str, float]] = {}

    async def _one(sid: str, text: str):
        nonlocal done
        async with sem:
            try:
                results[sid] = await synthesize_cached(text, cfg)
            except TTSError as exc:
                raise TTSError(f"Câu \"{text[:40]}…\": {exc}") from exc
        done += 1
        if on_progress:
            on_progress(done, total)

    tasks = [asyncio.ensure_future(_one(sid, t)) for sid, t in texts.items()]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:          # 1 câu lỗi → dừng các câu còn lại, không gọi Edge vô ích
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return results


async def synthesize_many(
    texts: dict[str, str], cfg: dict,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_note: Optional[Callable[[str], None]] = None,
) -> dict[str, tuple[str, float]]:
    """Tạo giọng đọc cho nhiều câu song song. texts: {sentence_id: speak_text}.

    Edge lỗi với giọng đang chọn → đọc lại CẢ video bằng giọng Edge còn lại (không trộn 2 giọng).
    """
    try:
        return await _synthesize_all(texts, cfg, on_progress)
    except TTSError as exc:
        alt = _alt_voice(cfg)
        if not alt:
            raise
        note = (f"⚠ Giọng {cfg.get('tts_voice') or 'vi-VN-HoaiMyNeural'} đang bị máy chủ Microsoft từ chối → "
                f"đọc cả video bằng giọng {alt['name']}. Muốn giữ giọng cũ thì thử lại sau ít phút.")
        log.warning("%s (%s)", note, exc)
        if on_note:
            on_note(note)
        try:
            return await _synthesize_all(texts, {**cfg, "tts_voice": alt["id"]}, on_progress)
        except TTSError:
            raise exc from None
