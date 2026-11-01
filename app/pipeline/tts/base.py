"""
base.py — Interface chung cho các engine TTS (Edge-TTS, VieNeu-TTS).

Engine chỉ cần tạo file âm thanh (mp3/wav...) cho một câu. Phần cache, chuyển WAV
và đo thời lượng nằm ở app/pipeline/tts/__init__.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class TTSError(RuntimeError):
    """Lỗi TTS, thông điệp tiếng Việt."""


class TTSBase(ABC):
    name = "tts"
    output_ext = ".mp3"
    concurrency = 4  # số câu tạo song song tối đa

    @abstractmethod
    async def synthesize(self, text: str, output_path: str, voice: str, speed: str) -> None:
        """Tạo file âm thanh cho *text* tại *output_path*."""


def speed_to_ratio(speed: str) -> float:
    """'+15%' → 1.15; '-10%' → 0.9."""
    try:
        return 1.0 + float(str(speed).replace("%", "").replace("+", "")) / 100.0
    except ValueError:
        return 1.0
