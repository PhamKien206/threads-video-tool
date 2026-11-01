"""
ocr.py — AI đọc chữ từ ảnh thẻ Threads (prompt B1: app/prompts/ocr.md).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from app.config import PROMPTS_DIR
from app.llm.base import LLMBase, image_size

MAX_SIDE_SENT = 2000  # khớp với load_image_for_llm
CONCURRENCY = 3


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Thiếu file prompt app/prompts/{name}")
    return path.read_text(encoding="utf-8").strip()


def _validate(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return "phải là một object JSON"
    if not isinstance(data.get("body"), str):
        return 'thiếu trường "body" kiểu chuỗi'
    box = data.get("author_box")
    if box is not None and not (isinstance(box, list) and len(box) == 4
                                and all(isinstance(v, (int, float)) for v in box)):
        return '"author_box" phải là [x1, y1, x2, y2] hoặc null'
    return None


_RE_PART = re.compile(r"^\s*\(?\d{1,2}\s*/\s*\d{1,2}\)?\s*$")


def clean_body(text: str) -> str:
    """Dọn những thứ model hay lỡ chép: dòng '1/7', 'Xem thêm', 'Dịch', khoảng trắng thừa."""
    lines = []
    for line in (text or "").replace("\r", "").split("\n"):
        s = line.strip()
        if _RE_PART.match(s) or s.lower() in {"xem thêm", "dịch", "trả lời", "see more", "translate"}:
            continue
        lines.append(line.rstrip())
    body = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", body)


def _to_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def ocr_card(llm: LLMBase, image_path: str) -> dict:
    """OCR một thẻ. Trả về dict đã chuẩn hóa; author_box theo pixel của ảnh gốc."""
    w, h = image_size(image_path)
    scale = min(1.0, MAX_SIDE_SENT / max(w, h))
    sw, sh = round(w * scale), round(h * scale)
    gemini = llm.name == "Gemini"
    if gemini:  # Gemini được huấn luyện trả khung theo [ymin, xmin, ymax, xmax] thang 0–1000
        note = "author_box ghi theo định dạng [ymin, xmin, ymax, xmax], chuẩn hóa thang 0–1000."
    else:
        note = f"Ảnh gửi kèm có kích thước {sw}×{sh} pixel; author_box = [x1, y1, x2, y2] theo pixel của kích thước này."
    prompt = load_prompt("ocr.md") + f"\n\n({note})"

    data = await llm.complete_json(prompt, image_path=image_path, validator=_validate)

    box = data.get("author_box")
    if box:
        x1, y1, x2, y2 = [float(v) for v in box]
        if gemini and max(x1, y1, x2, y2) <= 1000:
            y1, x1, y2, x2 = x1 / 1000 * sh, y1 / 1000 * sw, x2 / 1000 * sh, y2 / 1000 * sw
        elif max(x1, y1, x2, y2) <= 1.0:          # model trả về tỉ lệ 0–1
            x1, x2, y1, y2 = x1 * sw, x2 * sw, y1 * sh, y2 * sh
        box = [int(x1 / scale), int(y1 / scale), int(x2 / scale), int(y2 / scale)]
        box = [max(0, min(box[0], w)), max(0, min(box[1], h)), max(0, min(box[2], w)), max(0, min(box[3], h))]
        if box[2] - box[0] < 5 or box[3] - box[1] < 5:
            box = None

    return {
        "body": clean_body(data.get("body", "")),
        "part_index": _to_int(data.get("part_index")),
        "part_total": _to_int(data.get("part_total")),
        "author_box": box,
        "is_reply": bool(data.get("is_reply")),
        "uncertain_words": [str(x) for x in (data.get("uncertain_words") or [])][:20],
    }


async def ocr_cards(llm: LLMBase, image_paths: list[str], on_done=None) -> list[dict | Exception]:
    """OCR nhiều thẻ song song (tối đa 3 cùng lúc). Lỗi của từng thẻ trả về dạng Exception."""
    sem = asyncio.Semaphore(max(1, getattr(llm, "concurrency", CONCURRENCY)))

    async def _one(p: str):
        async with sem:
            try:
                res = await ocr_card(llm, p)
            except Exception as exc:
                res = exc
            if on_done:
                on_done(p, res)
            return res

    return await asyncio.gather(*[_one(p) for p in image_paths])
