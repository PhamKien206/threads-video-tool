"""
claude.py — Nhà cung cấp Anthropic Claude (đọc được ảnh).
"""
from __future__ import annotations

import base64
from typing import Optional

import anthropic

from app.llm.base import LLMBase, LLMError

MAX_TOKENS = 16000


class ClaudeLLM(LLMBase):
    name = "Claude"
    default_model = "claude-sonnet-5-5"

    def __init__(self, api_key: str, model: str = "") -> None:
        super().__init__(api_key, model)
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    async def _generate(self, prompt: str, image: Optional[tuple[bytes, str]] = None) -> str:
        content: list[dict] = []
        if image:
            data, mime = image
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime,
                           "data": base64.standard_b64encode(data).decode("ascii")},
            })
        content.append({"type": "text", "text": prompt})

        # fallbacks="default": nếu model chính từ chối vì bộ lọc an toàn,
        # API tự chạy lại yêu cầu trên model dự phòng phù hợp.
        response = await self._client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": content}],
        )
        if response.stop_reason == "refusal":
            raise LLMError("Claude từ chối xử lý nội dung này (bộ lọc an toàn).")
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason == "max_tokens" and not text.rstrip().endswith(("}", "]")):
            raise RuntimeError("Phản hồi bị cắt ngang vì quá dài.")
        return text

    def friendly_error(self, exc: Exception) -> str:
        if isinstance(exc, anthropic.AuthenticationError):
            return "API key Claude không hợp lệ. Kiểm tra lại trong Cài đặt."
        if isinstance(exc, anthropic.PermissionDeniedError):
            return "API key Claude không có quyền dùng model này."
        if isinstance(exc, anthropic.NotFoundError):
            return f"Không tìm thấy model '{self.model}'. Kiểm tra ô Model trong Cài đặt."
        if isinstance(exc, anthropic.RateLimitError):
            return "Claude đang giới hạn tốc độ (rate limit). Thử lại sau ít phút."
        if isinstance(exc, anthropic.BadRequestError):
            msg = getattr(exc, "message", str(exc))
            if "credit" in msg.lower():
                return "Tài khoản Claude hết quota/credit. Nạp thêm tại console.anthropic.com."
            return f"Yêu cầu không hợp lệ: {msg}"
        if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
            return "Máy chủ Anthropic đang lỗi hoặc quá tải. Thử lại sau."
        if isinstance(exc, anthropic.APITimeoutError):
            return "Gọi Claude bị quá thời gian. Kiểm tra kết nối mạng."
        if isinstance(exc, anthropic.APIConnectionError):
            return "Không kết nối được tới Claude. Kiểm tra mạng."
        return str(exc)
