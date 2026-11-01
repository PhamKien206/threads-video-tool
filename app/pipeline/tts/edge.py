"""
edge.py — Giọng đọc Microsoft Edge (online, miễn phí) qua thư viện edge-tts.

Máy chủ Edge đôi khi trả "No audio was received" cho MỘT câu cụ thể (thường khi có tốc độ ≠ 0%,
ký tự lạ, hoặc câu quá dài). Thứ tự xử lý khi lỗi:
  1. Thử lại đúng câu, đúng tốc độ (2 lần, có giãn cách).
  2. Đọc ở tốc độ +0% rồi tăng tốc bằng FFmpeg (atempo) cho đúng tốc độ cài đặt.
  3. Đổi nhẹ dấu câu (bỏ dấu chấm/phẩy cuối, thay "!?" bằng ".") rồi đọc ở +0% + atempo.
  4. Cắt câu làm 2–3 đoạn, đọc từng đoạn ở +0% rồi ghép lại + atempo.
"""
from __future__ import annotations

import asyncio
import os
import random
import re
import uuid
from pathlib import Path

from app.pipeline.tts.base import TTSBase, TTSError, speed_to_ratio
from app.utils import run_ffmpeg

VOICES = [
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My (nữ)"},
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (nam)"},
]


def _rate(speed: str) -> int:
    try:
        return int(round(float(str(speed).replace("%", "").replace("+", "") or 0)))
    except ValueError:
        return 0


def _variants(text: str) -> list[str]:
    v = [text]
    a = re.sub(r"[.!?]+$", "", text).strip()
    b = re.sub(r"[!?;:]", ".", a)
    c = re.sub(r"[,.!?;:]", " ", text)
    c = re.sub(r"\s{2,}", " ", c).strip()
    for x in (a, b, c):
        if x and x not in v:
            v.append(x)
    return v


def _split(text: str) -> list[str]:
    """Cắt câu thành 2–3 đoạn, ưu tiên tại dấu phẩy, không thì giữa câu."""
    parts = [p.strip() for p in re.split(r"(?<=[,;:])\s+", text) if p.strip()]
    if len(parts) >= 2:
        # gộp lại thành tối đa 3 đoạn cân bằng
        while len(parts) > 3:
            i = min(range(len(parts) - 1), key=lambda k: len(parts[k]) + len(parts[k + 1]))
            parts[i:i + 2] = [parts[i] + " " + parts[i + 1]]
        return parts
    words = text.split()
    if len(words) < 4:
        return [text]
    mid = len(words) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


class EdgeTTS(TTSBase):
    name = "Edge-TTS"
    output_ext = ".mp3"
    concurrency = 2  # máy chủ Edge hay trả "No audio received" khi gọi song song nhiều

    async def _try(self, text: str, voice: str, rate: int, out: str, tries: int = 1) -> bool:
        import edge_tts
        for attempt in range(tries):
            try:
                await edge_tts.Communicate(text=text, voice=voice, rate=f"{rate:+d}%").save(out)
                if os.path.exists(out) and os.path.getsize(out) > 0:
                    return True
            except Exception as exc:  # noqa: BLE001
                self._last = exc
            if attempt < tries - 1:
                await asyncio.sleep(0.8 * (attempt + 1) + random.uniform(0, 0.5))
        return False

    async def _speedup(self, src: str, dst: str, ratio: float) -> None:
        if abs(ratio - 1.0) < 0.01:
            os.replace(src, dst)
            return
        ratio = max(0.5, min(2.0, ratio))
        await asyncio.to_thread(run_ffmpeg, ["-i", src, "-filter:a", f"atempo={ratio:.3f}", dst])

    async def _pieces(self, text: str, voice: str, files: list, made: list, tmp, depth: int) -> bool:
        """Đọc *text* theo từng đoạn nhỏ (ở +0%), thêm file vào *files* theo đúng thứ tự."""
        parts = _split(text)
        if len(parts) == 1 and depth > 0:
            parts = [text]
        for part in parts:
            raw = tmp(); made.append(raw)
            ok = False
            if depth > 0 or len(parts) > 1:
                for variant in _variants(part):
                    if await self._try(variant, voice, 0, raw, tries=2):
                        ok = True
                        break
            if ok:
                files.append(raw)
            elif depth < 2 and len(part.split()) >= 4:
                if not await self._pieces(part, voice, files, made, tmp, depth + 1):
                    return False
            else:
                return False
        return True

    async def synthesize(self, text: str, output_path: str, voice: str, speed: str) -> None:
        text = (text or "").strip()
        if not text:
            raise TTSError("Câu đọc rỗng.")
        self._last = None
        rate = _rate(speed)
        ratio = speed_to_ratio(f"{rate:+d}%")
        tmpdir = Path(output_path).parent
        tmp = lambda: str(tmpdir / f"edge_{uuid.uuid4().hex}.mp3")  # noqa: E731
        made: list[str] = []
        try:
            # 1) đúng câu, đúng tốc độ
            if await self._try(text, voice, rate, output_path, tries=2):
                return
            # 2) + 3) tốc độ 0% (+ các biến thể dấu câu) rồi tăng tốc bằng FFmpeg
            for variant in _variants(text):
                raw = tmp(); made.append(raw)
                if await self._try(variant, voice, 0, raw, tries=2):
                    await self._speedup(raw, output_path, ratio)
                    return
            # 4) cắt nhỏ câu (tối đa 2 cấp), đọc từng đoạn rồi ghép
            files: list[str] = []
            if await self._pieces(text, voice, files, made, tmp, depth=0) and len(files) > 1:
                joined = tmp(); made.append(joined)
                lst = tmp() + ".txt"; made.append(lst)
                Path(lst).write_text("".join(f"file '{Path(f).as_posix()}'\n" for f in files), encoding="utf-8")
                await asyncio.to_thread(run_ffmpeg, ["-f", "concat", "-safe", "0", "-i", lst,
                                                     "-c:a", "libmp3lame", "-q:a", "3", joined])
                await self._speedup(joined, output_path, ratio)
                return
        finally:
            for f in made:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        raise TTSError(
            f"Edge-TTS không tạo được giọng đọc sau nhiều cách thử ({self._last}). "
            "Kiểm tra mạng, sửa lại câu này ở bước Duyệt, hoặc chọn VieNeu-TTS (offline) trong Cài đặt."
        )
