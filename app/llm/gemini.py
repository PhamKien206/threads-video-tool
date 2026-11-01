"""
gemini.py — Nhà cung cấp Google Gemini (SDK google-genai, đọc được ảnh).
"""
from __future__ import annotations

from typing import Optional

from google import genai
from google.genai import types

from app.llm.base import LLMBase, LLMError


class GeminiLLM(LLMBase):
    name = "Gemini"
    default_model = "gemini-3.8-flash"

    def __init__(self, api_key: str, model: str = "") -> None:
        super().__init__(api_key, model)
        self._client = genai.Client(api_key=api_key)

    async def _generate(self, prompt: str, image: Optional[tuple[bytes, str]] = None) -> str:
        parts: list = []
        if image:
            data, mime = image
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        parts.append(prompt)
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        text = response.text or ""
        if not text:
            reason = ""
            try:
                reason = str(response.candidates[0].finish_reason)
            except Exception:
                pass
            if "SAFETY" in reason or "PROHIBITED" in reason:
                raise LLMError("Gemini từ chối nội dung này vì chính sách an toàn.")
            raise RuntimeError(f"Gemini trả về rỗng ({reason or 'không rõ lý do'}).")
        return text

    def friendly_error(self, exc: Exception) -> str:
        msg = str(exc)
        if "API_KEY_INVALID" in msg or "API key not valid" in msg:
            return "API key Gemini không hợp lệ. Kiểm tra lại trong Cài đặt."
        if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            return "Gemini hết quota (hạn mức miễn phí theo ngày/phút). Thử lại sau hoặc nâng cấp."
        if "NOT_FOUND" in msg or "is not found" in msg:
            return (f"Không tìm thấy model '{self.model}'. Kiểm tra ô Model trong Cài đặt "
                    "(gợi ý: gemini-3.8-flash hoặc gemini-3.5-flash-lite).")
        if "timeout" in msg.lower() or "deadline" in msg.lower():
            return "Gọi Gemini bị quá thời gian. Kiểm tra kết nối mạng."
        return msg
