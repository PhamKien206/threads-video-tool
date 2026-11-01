"""
openai_llm.py — Nhà cung cấp dùng API "tương thích OpenAI" (đọc được ảnh).

Một class dùng chung cho:
  - OpenAI          (base_url mặc định api.openai.com, hoặc Base URL tùy chọn trong Cài đặt)
  - Z.ai (GLM)      https://api.z.ai/api/paas/v4/        model mặc định glm-5.3-flash
  - OpenRouter      https://openrouter.ai/api/v1         model mặc định z-ai/glm-5.3-flash:free
"""
from __future__ import annotations

import asyncio
import base64
import difflib
from typing import Optional

import openai
from openai import AsyncOpenAI

from app.llm.base import LLMBase, LLMError

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT = 20  # giây


class OpenAILLM(LLMBase):
    name = "OpenAI"
    default_model = "gpt-4o-mini"
    default_base_url: Optional[str] = None
    billing_hint = "Nạp thêm credit tại platform.openai.com."
    extra_headers: dict = {}

    def __init__(self, api_key: str, model: str = "", base_url: str = "") -> None:
        super().__init__(api_key, model)
        self.base_url = (base_url or "").strip() or self.default_base_url
        self._client = AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=1,
                                   default_headers=self.extra_headers or None)
        self._json_mode = True   # một số model không hỗ trợ response_format → tự tắt

    async def _create(self, content: list[dict]):
        kwargs: dict = {"model": self.model, "messages": [{"role": "user", "content": content}]}
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return await self._client.chat.completions.create(**kwargs)

    async def _generate(self, prompt: str, image: Optional[tuple[bytes, str]] = None) -> str:
        content: list[dict] = []
        if image:
            data, mime = image
            url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        content.append({"type": "text", "text": prompt})

        response = None
        for attempt in range(RATE_LIMIT_RETRIES + 2):
            try:
                response = await self._create(content)
                break
            except openai.BadRequestError as exc:
                # Model không hỗ trợ JSON mode → gọi lại không có response_format (base.py tự tách JSON)
                low = str(exc).lower()
                if _is_blocked_client(exc):
                    raise LLMError(f"{self.name}: {self.friendly_error(exc)}") from exc
                if self._json_mode and ("response_format" in low or "json" in low):
                    self._json_mode = False
                    continue
                raise
            except openai.RateLimitError as exc:
                if _is_out_of_money(exc) or attempt >= RATE_LIMIT_RETRIES:
                    # Lỗi "dứt khoát": báo ngay (không để lớp ngoài thử lại thêm), để nhà cung cấp dự phòng tiếp quản
                    raise LLMError(f"{self.name}: {self.friendly_error(exc)}") from exc
                await asyncio.sleep(RATE_LIMIT_WAIT)
            except (openai.NotFoundError, openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                # 401 "unauthorized client" cũng đi qua đây → friendly_error báo rõ bị chặn
                raise LLMError(f"{self.name}: {self.friendly_error(exc)}") from exc
        if response is None or not response.choices:
            raise RuntimeError(f"{self.name} trả về rỗng.")
        return response.choices[0].message.content or ""

    async def suggest_models(self, limit: int = 5) -> list[str]:
        """Gợi ý model gần đúng (ưu tiên model đọc được ảnh) khi người dùng gõ sai tên."""
        try:
            page = await self._client.models.list()
            ids = [m.id for m in page.data]
        except Exception:
            return []
        vision = [i for i in ids if any(t in i.lower() for t in ("v", "vision", "flash", "4o", "omni"))] or ids
        close = difflib.get_close_matches(self.model, vision, n=limit, cutoff=0.3)
        return close or vision[:limit]

    async def test_connection(self) -> str:
        try:
            return await super().test_connection()
        except Exception as exc:
            if "Không tìm thấy model" in str(exc):
                sug = await self.suggest_models()
                if sug:
                    raise type(exc)(f"{exc} Gợi ý: {', '.join(sug)}") from exc
            raise

    def friendly_error(self, exc: Exception) -> str:
        msg = str(exc)
        if _is_blocked_client(exc):
            return (f"Dịch vụ {self.base_url or 'OpenAI'} chặn tool này (content-blocked / unauthorized client). "
                    "Một số dịch vụ trung gian như AgentRouter chỉ cho dùng từ công cụ lập trình (Claude Code, Codex…), "
                    "không cho app khác gọi. Hãy đổi sang nhà cung cấp khác trong Cài đặt (Gemini, Z.ai, OpenRouter, Ollama).")
        if isinstance(exc, openai.AuthenticationError):
            return f"API key {self.name} sai hoặc đã bị xóa. Kiểm tra lại trong Cài đặt."
        if isinstance(exc, openai.PermissionDeniedError):
            return f"{self.name} từ chối truy cập (key không có quyền dùng model '{self.model}')."
        if isinstance(exc, openai.NotFoundError):
            return f"Không tìm thấy model '{self.model}'. Kiểm tra ô Model trong Cài đặt."
        if _is_out_of_money(exc):
            return f"Tài khoản {self.name} hết số dư / hết quota. {self.billing_hint}"
        if isinstance(exc, openai.RateLimitError):
            return (f"{self.name} đang giới hạn tốc độ (rate limit, thường gặp ở bản miễn phí). "
                    "Đợi 1 phút hoặc đổi sang bản trả phí.")
        if isinstance(exc, openai.APITimeoutError):
            return f"Gọi {self.name} bị quá thời gian. Kiểm tra kết nối mạng."
        if isinstance(exc, openai.APIConnectionError):
            return f"Không kết nối được tới {self.name} ({self.base_url or 'api.openai.com'}). Kiểm tra mạng / Base URL."
        return msg


class ZaiLLM(OpenAILLM):
    name = "Z.ai"
    default_model = "glm-5.3-flash"
    default_base_url = ZAI_BASE_URL
    billing_hint = "Vào z.ai → Billing để nạp tiền (KHÔNG cần mua Coding Plan)."


class OpenRouterLLM(OpenAILLM):
    name = "OpenRouter"
    default_model = "z-ai/glm-5.3-flash:free"
    default_base_url = OPENROUTER_BASE_URL
    billing_hint = "Nạp credit tại openrouter.ai/settings/credits, hoặc dùng model có đuôi :free."
    extra_headers = {"HTTP-Referer": "http://localhost:8000", "X-Title": "Threads Video Tool"}


def _is_blocked_client(exc: Exception) -> bool:
    """Dịch vụ trung gian từ chối cả ứng dụng (không phải lỗi nội dung prompt)."""
    low = str(exc).lower()
    return any(k in low for k in ("content-blocked", "unauthorized client", "unauthorized_client"))


def _is_out_of_money(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    low = str(exc).lower()
    return status == 402 or any(k in low for k in (
        "insufficient_quota", "insufficient balance", "insufficient credits", "余额不足",
        "balance", "arrears", "payment required"))
