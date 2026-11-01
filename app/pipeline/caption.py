"""
caption.py — Gợi ý caption + hashtag đăng bài (prompt B5: app/prompts/caption.md).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.llm.base import LLMBase
from app.pipeline.ocr import load_prompt


def _validator(data: Any) -> Optional[str]:
    if not isinstance(data, dict) or not str(data.get("caption", "")).strip():
        return 'cần {"caption": "...", "hashtags": [...]}'
    return None


def _clean_tags(tags) -> list[str]:
    out = []
    for t in tags if isinstance(tags, list) else []:
        t = re.sub(r"\s+", "", str(t))
        if t:
            out.append(t if t.startswith("#") else f"#{t}")
    return out[:6]


def clean_topic(text: str, max_words: int = 14) -> str:
    """Chuẩn hóa chủ đề: bỏ ký tự lạ/dấu câu/emoji, tối đa *max_words* từ."""
    t = re.sub(r"#\S+", " ", str(text or ""))
    t = re.sub(r"[^\w\s-]", " ", t)
    t = re.sub(r"[_\s]+", " ", t).strip(" -")
    words = t.split()[:max_words]
    t = " ".join(words)
    return t[:1].upper() + t[1:] if t else ""


def fallback_topic(plan: dict) -> str:
    """Không có AI: lấy tiêu đề gợi ý, hoặc 8 từ đầu của câu đầu tiên (bỏ 'Topic:')."""
    title = plan.get("title_suggestion") or ""
    if title:
        return clean_topic(title)
    first = next((s.get("display_text", "") for c in plan.get("cards", []) for s in c.get("sentences", [])), "")
    first = re.sub(r"^\s*(topic|chủ đề)\s*[:：-]\s*", "", first, flags=re.IGNORECASE)
    return clean_topic(first, 8)


async def suggest_caption(plan: dict, llm: LLMBase | None) -> dict:
    """Trả về {"title", "caption", "hashtags", "topic"}. Không có AI → dùng gợi ý từ planner."""
    title = plan.get("title_suggestion") or ""
    fallback_tags = plan.get("hashtags") or ["#threads", "#xuhuong"]
    if llm is None:
        return {"title": title, "caption": title or "Bạn nghĩ sao về chuyện này? Bình luận nhé!",
                "hashtags": _clean_tags(fallback_tags), "topic": fallback_topic(plan)}
    full = "\n".join(s["display_text"] for c in plan.get("cards", []) for s in c.get("sentences", []))
    data = await llm.complete_json(load_prompt("caption.md").replace("{{FULL_TEXT}}", full[:6000]),
                                   validator=_validator)
    return {"title": title, "caption": str(data.get("caption", "")).strip(),
            "hashtags": _clean_tags(data.get("hashtags")) or _clean_tags(fallback_tags),
            "topic": clean_topic(data.get("topic", "")) or fallback_topic(plan)}
