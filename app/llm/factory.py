"""
factory.py — Tạo đối tượng LLM theo cấu hình (kèm nhà cung cấp dự phòng nếu có).
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_api_key, get_config
from app.llm.base import LLMBase, LLMError

log = logging.getLogger("ttv.llm")

PROVIDERS = ("gemini", "claude", "openai", "zai", "openrouter", "ollama")
PROVIDER_LABELS = {"gemini": "Gemini", "claude": "Claude", "openai": "OpenAI",
                   "zai": "Z.ai (GLM)", "openrouter": "OpenRouter", "ollama": "Ollama (máy này)"}

# Lỗi đáng để chuyển sang nhà cung cấp dự phòng (hết tiền / hết hạn mức / rate limit / mất kết nối)
_SWITCH_HINTS = ("hết quota", "hết số dư", "giới hạn tốc độ", "rate limit", "không kết nối",
                 "quá thời gian", "không tìm thấy model", "trả về rỗng", "chưa tải model", "ollama",
                 "chưa nhập api key", "chặn tool này")


def _norm(provider: str | None) -> str:
    p = (provider or "gemini").lower().strip()
    return {"gpt": "openai", "z.ai": "zai", "glm": "zai"}.get(p, p)


def make_llm(provider: str, cfg: dict, model: str = "") -> LLMBase:
    provider = _norm(provider)
    if provider == "ollama":
        from app.llm.ollama import OllamaLLM
        return OllamaLLM(cfg.get("ollama_url") or "", model or cfg.get("ollama_model") or "",
                         cfg.get("ollama_vision_model") or "")
    key = get_api_key(cfg, provider)
    model = (model or "").strip()
    if provider == "gemini":
        from app.llm.gemini import GeminiLLM
        return GeminiLLM(key, model)
    if provider == "claude":
        from app.llm.claude import ClaudeLLM
        return ClaudeLLM(key, model)
    if provider == "openai":
        from app.llm.openai_llm import OpenAILLM
        return OpenAILLM(key, model, cfg.get("openai_base_url") or "")
    if provider == "zai":
        from app.llm.openai_llm import ZaiLLM
        return ZaiLLM(key, model)
    if provider == "openrouter":
        from app.llm.openai_llm import OpenRouterLLM
        return OpenRouterLLM(key, model)
    raise LLMError(f"Nhà cung cấp AI không hỗ trợ: '{provider}'. Chọn một trong: {', '.join(PROVIDERS)}.")


class FallbackLLM:
    """Gọi nhà cung cấp chính; nếu lỗi kiểu hết tiền/hết hạn mức/rate limit thì tự chuyển sang dự phòng."""

    def __init__(self, primary: LLMBase, backup: LLMBase) -> None:
        self.primary, self.backup = primary, backup
        self.name = primary.name
        self.model = primary.model
        self.switched = False
        self.concurrency = min(getattr(primary, "concurrency", 3), getattr(backup, "concurrency", 3))

    async def complete_json(self, *args: Any, **kwargs: Any) -> Any:
        if not self.switched:
            try:
                return await self.primary.complete_json(*args, **kwargs)
            except LLMError as exc:
                if not any(h in str(exc).lower() for h in _SWITCH_HINTS):
                    raise
                log.warning("AI %s lỗi (%s) → chuyển sang dự phòng %s (%s)",
                            self.primary.name, exc, self.backup.name, self.backup.model)
                self.switched = True
                self.name = f"{self.backup.name} (dự phòng)"
                self.model = self.backup.model
        return await self.backup.complete_json(*args, **kwargs)

    async def test_connection(self) -> str:
        lines = []
        for label, llm in (("Chính", self.primary), ("Dự phòng", self.backup)):
            try:
                lines.append(f"{label}: {await llm.test_connection()}")
            except Exception as exc:
                lines.append(f"{label}: ❌ {exc}")
        msg = " | ".join(lines)
        if all("❌" in l for l in lines):
            raise LLMError(msg)
        return msg


def get_llm(cfg: dict | None = None):
    cfg = cfg or get_config()
    prov = _norm(cfg.get("llm_provider"))
    # Ollama dùng ô model riêng (ollama_model); llm_model chỉ áp cho nhà cung cấp có API
    primary = make_llm(prov, cfg, "" if prov == "ollama" else (cfg.get("llm_model") or ""))
    fb = _norm(cfg.get("fallback_provider") or "") if cfg.get("fallback_provider") else ""
    if fb and fb != prov and (fb == "ollama" or get_api_key(cfg, fb)):
        try:
            backup = make_llm(fb, cfg, "" if fb == "ollama" else (cfg.get("fallback_model") or ""))
        except LLMError:
            return primary
        return FallbackLLM(primary, backup)
    return primary
