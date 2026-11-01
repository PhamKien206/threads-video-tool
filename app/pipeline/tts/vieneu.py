"""
vieneu.py — Giọng đọc offline VieNeu-TTS (tùy chọn, cần cài riêng).

VieNeu-TTS không nằm trong requirements.txt vì nặng (cần tải model). Cài theo hướng dẫn
trong README. Module này thử các cách gọi phổ biến của thư viện; nếu không có thì báo lỗi rõ ràng.
"""
from __future__ import annotations

import asyncio

from app.pipeline.tts.base import TTSBase, TTSError

INSTALL_GUIDE = (
    "Chưa cài VieNeu-TTS (giọng đọc offline). Cách cài: mở cửa sổ dòng lệnh trong thư mục tool, "
    "kích hoạt môi trường (.venv) rồi chạy: pip install vieneu — sau đó khởi động lại tool. "
    "Hoặc chọn lại Edge-TTS trong Cài đặt."
)


class VieNeuTTS(TTSBase):
    name = "VieNeu-TTS"
    output_ext = ".wav"
    _engine = None

    @classmethod
    def _load(cls):
        if cls._engine is not None:
            return cls._engine
        try:
            import vieneu  # type: ignore[import-not-found]
        except ImportError as exc:
            raise TTSError(INSTALL_GUIDE) from exc
        factory = getattr(vieneu, "Vieneu", None) or getattr(vieneu, "VieNeuTTS", None)
        if factory is None:
            raise TTSError("Phiên bản VieNeu-TTS đã cài không có lớp Vieneu/VieNeuTTS. Hãy cập nhật: pip install -U vieneu")
        cls._engine = factory()
        return cls._engine

    async def synthesize(self, text: str, output_path: str, voice: str, speed: str) -> None:
        def _run():
            engine = self._load()
            try:
                kwargs = {"text": text}
                if voice and not voice.startswith("vi-VN-"):
                    kwargs["voice"] = voice
                audio = engine.infer(**kwargs)
                if hasattr(engine, "save"):
                    engine.save(audio, output_path)
                else:
                    import soundfile as sf  # type: ignore[import-not-found]
                    sf.write(output_path, audio, getattr(engine, "sample_rate", 24000))
            except TTSError:
                raise
            except Exception as exc:
                raise TTSError(f"VieNeu-TTS lỗi khi đọc câu: {exc}") from exc

        await asyncio.to_thread(_run)
