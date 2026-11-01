"""
comment_filter.py — Lọc bình luận: lọc thô bằng code + AI chọn 3–6 bình luận hay (prompt B3).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.llm.base import LLMBase
from app.pipeline.ocr import load_prompt

MIN_WORDS = 5
MAX_WORDS = 80
MAX_CANDIDATES = 25
DUP_THRESHOLD = 0.8

_RE_URL = re.compile(r"https?://\S+|www\.\S+|\b\S+\.(?:com|net|vn|io|me|ly)\b", re.IGNORECASE)
_RE_MENTION = re.compile(r"@[\w.]+")
_RE_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF‍️]+")


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _similar(a: str, b: str) -> float:
    sa, sb = set(_words(a)), set(_words(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def strip_mentions(text: str) -> str:
    """Bỏ @tag (tránh lộ tên người khác trên thẻ)."""
    return re.sub(r"\s{2,}", " ", _RE_MENTION.sub("", text)).strip(" ,:")


def filter_basic(comments: list[dict]) -> list[dict]:
    """Bỏ: chỉ có @tag, chỉ có emoji, có link, dưới 5 chữ, trên 80 chữ, trùng nhau."""
    kept: list[dict] = []
    for c in comments:
        text = (c.get("text") or "").strip()
        if not text or _RE_URL.search(text):
            continue
        without_tags = strip_mentions(text)
        if not without_tags:
            continue  # chỉ có @tag
        if not _RE_EMOJI.sub("", without_tags).strip(" .,!?"):
            continue  # chỉ có emoji
        n = len(_words(without_tags))
        if n < MIN_WORDS or n > MAX_WORDS:
            continue
        if any(_similar(without_tags, k["text"]) >= DUP_THRESHOLD for k in kept):
            continue
        kept.append({**c, "text": without_tags})
    kept.sort(key=lambda c: (c.get("likes", 0) * 1.0 + c.get("replies", 0) * 3.0), reverse=True)
    return kept[:MAX_CANDIDATES]


def _validator(ids: set[str], lo: int, hi: int):
    def _v(data: Any) -> Optional[str]:
        if not isinstance(data, dict) or not isinstance(data.get("selected"), list):
            return 'cần object có "selected" (danh sách) và "order"'
        sel = [str(s.get("id")) for s in data["selected"] if isinstance(s, dict)]
        bad = [i for i in sel if i not in ids]
        if bad:
            return f"id không có trong danh sách ứng viên: {', '.join(bad[:5])}"
        # Chọn ít hơn {lo} vẫn nhận (tự bổ sung theo lượt thích sau), thừa thì cắt bớt.
        # Không bắt AI làm lại vì model local nhỏ hay đếm sai, mỗi lần làm lại tốn 30–60 giây.
        if not sel:
            return f"phải chọn từ {lo} đến {hi} bình luận (đang chọn 0)"
        return None
    return _v


async def select_comments(comments: list[dict], post_text: str, cfg: dict,
                          llm: LLMBase | None) -> list[dict]:
    """Chọn và sắp thứ tự trình chiếu. Không có AI → lấy theo lượt thích."""
    lo = int(cfg.get("comment_min", 3))
    hi = max(lo, int(cfg.get("comment_max", 6)))
    if not comments:
        return []
    if llm is None or len(comments) <= lo:
        return comments[:hi]

    by_id = {str(c["id"]): c for c in comments}
    payload = [{"id": str(c["id"]), "text": c["text"], "likes": c.get("likes", 0),
                "replies": c.get("replies", 0)} for c in comments]
    prompt = (load_prompt("comment_filter.md")
              .replace("{{POST_TEXT}}", post_text)
              .replace("{{COMMENTS_JSON}}", json.dumps(payload, ensure_ascii=False, indent=1))
              .replace("{{MIN}}", str(lo)).replace("{{MAX}}", str(hi)))
    data = await llm.complete_json(prompt, validator=_validator(set(by_id), lo, hi))

    selected = {str(s["id"]): s for s in data.get("selected", []) if isinstance(s, dict)}
    order = [str(i) for i in data.get("order", []) if str(i) in selected]
    order += [i for i in selected if i not in order]
    out = []
    for cid in order[:hi]:
        c = dict(by_id[cid])
        c["stance"] = selected[cid].get("stance")
        c["reason"] = selected[cid].get("reason")
        out.append(c)
    if len(out) < lo:  # AI chọn thiếu → bổ sung bình luận nhiều lượt thích nhất chưa được chọn
        taken = {str(c["id"]) for c in out}
        rest = sorted((c for c in comments if str(c["id"]) not in taken),
                      key=lambda c: c.get("likes", 0), reverse=True)
        out += [dict(c) for c in rest[: lo - len(out)]]
    return out


def anonymize(comments: list[dict]) -> list[dict]:
    """Người bình luận hiển thị là 'Người dùng 1, 2…'."""
    mapping: dict[str, str] = {}
    out = []
    for c in comments:
        key = c.get("username") or f"#{c.get('id')}"
        if key not in mapping:
            mapping[key] = f"Người dùng {len(mapping) + 1}"
        out.append({**c, "display_name": mapping[key], "username": None})
    return out
