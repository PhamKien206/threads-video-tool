"""
base.py — Interface chung cho mọi nhà cung cấp LLM (Gemini, Claude, OpenAI).

Mỗi provider chỉ cần cài đặt `_generate(prompt, image_path)` trả về chuỗi văn bản.
Lớp cơ sở lo phần: tách JSON, kiểm tra schema, retry 2 lần và gửi lại kèm thông báo lỗi.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

MAX_RETRIES = 2

# validator(data) -> None nếu hợp lệ, hoặc chuỗi mô tả lỗi
Validator = Callable[[Any], Optional[str]]


class LLMError(RuntimeError):
    """Lỗi gọi LLM, thông điệp đã là tiếng Việt dễ hiểu."""


class LLMBase(ABC):
    name = "llm"

    def __init__(self, api_key: str, model: str = "") -> None:
        if not api_key:
            raise LLMError(
                f"Chưa nhập API key cho {self.name}. Vào trang Cài đặt → AI để nhập key."
            )
        self.api_key = api_key
        self.model = model or self.default_model

    default_model = ""

    # ------------------------------------------------------------------ #
    @abstractmethod
    async def _generate(self, prompt: str, image: Optional[tuple[bytes, str]] = None) -> str:
        """Gửi prompt (kèm ảnh nếu có: (bytes, mime)) và trả về văn bản thô."""

    def friendly_error(self, exc: Exception) -> str:
        return str(exc)

    # ------------------------------------------------------------------ #
    async def complete_json(
        self,
        prompt: str,
        image_path: str | None = None,
        validator: Validator | None = None,
    ) -> Any:
        """Gọi LLM, trả về JSON đã parse. Retry tối đa 2 lần.

        Nếu JSON hỏng hoặc sai schema, lần gọi sau gửi kèm thông báo lỗi để model tự sửa.
        """
        image = load_image_for_llm(image_path) if image_path else None
        current_prompt = prompt
        last_err = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                text = await self._generate(current_prompt, image)
            except LLMError:
                raise
            except Exception as exc:  # lỗi mạng / API
                last_err = self.friendly_error(exc)
                if _is_fatal(last_err) or attempt == MAX_RETRIES:
                    raise LLMError(f"{self.name}: {last_err}") from exc
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            try:
                data = parse_json_response(text)
            except ValueError as exc:
                last_err = str(exc)
            else:
                problem = validator(data) if validator else None
                if not problem:
                    return data
                last_err = f"JSON sai schema: {problem}"

            if attempt < MAX_RETRIES:
                current_prompt = (
                    f"{prompt}\n\n---\nLần trả lời trước của bạn KHÔNG hợp lệ: {last_err}\n"
                    "Hãy trả lời lại, CHỈ gồm một JSON đúng schema đã yêu cầu, không kèm giải thích."
                )
        raise LLMError(f"{self.name} trả về dữ liệu không hợp lệ sau {MAX_RETRIES + 1} lần thử: {last_err}")

    async def test_connection(self) -> str:
        data = await self.complete_json('Trả về đúng JSON sau: {"ok": true}')
        if isinstance(data, dict) and data.get("ok") is True:
            return f"Kết nối {self.name} ({self.model}) thành công."
        return f"{self.name} trả lời được nhưng nội dung lạ: {data!r}"


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _is_fatal(msg: str) -> bool:
    low = msg.lower()
    return "api key" in low or "không hợp lệ" in low or "hết quota" in low or "từ chối" in low


def parse_json_response(text: str) -> Any:
    """Tách JSON từ phản hồi: chấp nhận JSON thuần, khối ```json```, hoặc JSON lẫn trong chữ."""
    if not text or not text.strip():
        raise ValueError("Phản hồi rỗng.")
    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())
    first = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if first >= 0:
        last = max(text.rfind("}"), text.rfind("]"))
        if last > first:
            candidates.append(text[first:last + 1])

    last_err: Exception | None = None
    for cand in candidates:
        for variant in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError as e:
                last_err = e
    raise ValueError(f"Không đọc được JSON ({last_err}). Đoạn đầu phản hồi: {text[:120]!r}")


def load_image_for_llm(image_path: str, max_side: int = 2000) -> tuple[bytes, str]:
    """Đọc ảnh, chuyển về PNG/JPEG (lấy khung đầu nếu là GIF/WebP động), thu nhỏ nếu quá lớn."""
    from PIL import Image

    path = Path(image_path)
    if not path.exists():
        raise LLMError(f"Không tìm thấy ảnh: {path.name}")
    with Image.open(path) as im:
        im.seek(0)
        im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        if im.mode == "RGBA":
            # nền trắng cho meme trong suốt để model nhìn rõ
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3])
            im = bg
        im.save(buf, "PNG")
    return buf.getvalue(), "image/png"


def image_size(image_path: str) -> tuple[int, int]:
    from PIL import Image
    with Image.open(image_path) as im:
        return im.size
