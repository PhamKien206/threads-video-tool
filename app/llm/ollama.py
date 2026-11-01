"""
ollama.py — AI chạy ngay trên máy qua Ollama (https://ollama.com), không cần API key.

Dùng API gốc của Ollama (/api/chat) thay vì cổng tương thích OpenAI để:
  - tắt chế độ "suy nghĩ" của Qwen (think=false) → trả JSON ngay, nhanh hơn;
  - ép định dạng JSON (format="json");
  - đặt num_ctx nhỏ cho vừa card 6 GB (GTX 1660 Ti…), keep_alive để không phải nạp lại model.

Mặc định: qwen3.5:4b — một model vừa đọc chữ vừa đọc ảnh (~3,4 GB), vừa card 6 GB.
"""
from __future__ import annotations

import base64
import io
import json
import re
from typing import AsyncIterator, Optional

import httpx

from app.llm.base import LLMBase, LLMError

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"
RECOMMENDED = [
    {"model": "qwen3.5:4b", "size": "3,4 GB", "note": "Khuyên dùng cho card 6 GB (GTX 1660 Ti, RTX 2060…) — đọc chữ + đọc ảnh"},
    {"model": "qwen3.5:2b", "size": "2,7 GB", "note": "Nhẹ hơn, cho máy yếu / card 4 GB"},
    {"model": "qwen3.5:9b", "size": "6,6 GB", "note": "Hay hơn nhưng cần card ≥ 8 GB (card 6 GB sẽ chạy chậm)"},
]
NUM_CTX = 16384   # qwen3.5 tốn rất ít bộ nhớ cho ngữ cảnh → vẫn vừa card 6 GB
TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=60.0, pool=10.0)
NUM_PREDICT = 4096    # chặn model nhỏ sinh chữ vô tận
BASE_OPTIONS = {"temperature": 0.3, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT}
# Model nhỏ hay bị kẹt lặp chữ ("token repeat limit reached") → gọi lại với cấu hình chống lặp
ANTI_REPEAT_OPTIONS = {"temperature": 0.7, "repeat_penalty": 1.3, "presence_penalty": 0.6,
                       "repeat_last_n": 256, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT}
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def _base(url: str) -> str:
    url = (url or DEFAULT_URL).strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _not_running(url: str) -> LLMError:
    return LLMError(
        f"Không kết nối được Ollama tại {url}. Hãy mở ứng dụng Ollama (biểu tượng con lạc đà ở khay hệ thống) "
        "rồi thử lại. Chưa cài thì tải ở https://ollama.com/download")


def _shrink(data: bytes, max_side: int = 1400) -> bytes:
    """Thu nhỏ ảnh cho model nhỏ: nhanh hơn, đỡ tốn VRAM, chữ vẫn đủ rõ."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) <= max_side:
                return data
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except Exception:
        return data


class OllamaLLM(LLMBase):
    name = "Ollama (máy này)"
    default_model = DEFAULT_MODEL
    concurrency = 1   # card 6 GB: xử lý tuần tự cho ổn định

    def __init__(self, url: str = "", model: str = "", vision_model: str = "") -> None:
        # Không cần API key → không gọi LLMBase.__init__ (vốn bắt buộc key)
        self.api_key = ""
        self.url = _base(url)
        self.model = (model or "").strip() or DEFAULT_MODEL
        self.vision_model = (vision_model or "").strip() or self.model
        self._think_ok = True

    # ------------------------------------------------------------------ #
    async def _post_chat(self, client: httpx.AsyncClient, body: dict) -> dict:
        try:
            r = await client.post(f"{self.url}/api/chat", json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise _not_running(self.url)
        except httpx.ReadTimeout:
            raise RuntimeError("Ollama trả lời quá lâu (quá thời gian). Máy đang bận hoặc model quá nặng cho card.")
        if r.status_code == 404 or "not found" in r.text.lower() and r.status_code >= 400:
            raise LLMError(f"Chưa tải model '{body['model']}'. Vào Cài đặt → AI → bấm \"Tải model\", "
                           f"hoặc mở PowerShell chạy: ollama pull {body['model']}")
        if r.status_code >= 400:
            msg = r.text[:300]
            if self._think_ok and "think" in msg.lower():
                raise _ThinkUnsupported()
            if "repeat" in msg.lower():
                raise _RepeatLoop(msg)
            raise RuntimeError(f"Ollama lỗi {r.status_code}: {msg}")
        return r.json()

    async def _generate(self, prompt: str, image: Optional[tuple[bytes, str]] = None) -> str:
        model = self.vision_model if image else self.model
        msg: dict = {"role": "user", "content": prompt}
        if image:
            msg["images"] = [base64.b64encode(_shrink(image[0])).decode("ascii")]
        body = {"model": model, "messages": [msg], "stream": False, "format": "json",
                "keep_alive": "15m", "options": dict(BASE_OPTIONS)}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for _ in range(3):
                if self._think_ok:
                    body["think"] = False
                else:
                    body.pop("think", None)
                try:
                    data = await self._post_chat(client, body)
                    break
                except _ThinkUnsupported:
                    self._think_ok = False   # model cũ không hỗ trợ "think" → gọi lại không có
                except _RepeatLoop as exc:
                    if body["options"] == ANTI_REPEAT_OPTIONS:
                        raise RuntimeError(f"Ollama bị lặp chữ (model quá nhỏ cho yêu cầu này): {exc}") from None
                    body["options"] = dict(ANTI_REPEAT_OPTIONS)
            else:
                raise RuntimeError("Ollama không trả lời.")
        text = ((data.get("message") or {}).get("content") or "").strip()
        text = _THINK_RE.sub("", text).strip()
        if not text:
            raise RuntimeError("Ollama trả về rỗng.")
        return text

    def friendly_error(self, exc: Exception) -> str:
        return str(exc)

    async def test_connection(self) -> str:
        st = await ollama_status(self.url)
        if not st["running"]:
            raise _not_running(self.url)
        names = {m["name"] for m in st["models"]}
        for m in {self.model, self.vision_model}:
            if m not in names and f"{m}:latest" not in names:
                raise LLMError(f"Ollama đang chạy nhưng chưa có model '{m}'. Bấm \"Tải model\" trong Cài đặt "
                               f"hoặc chạy: ollama pull {m}")
        msg = await super().test_connection()
        gpu = await gpu_usage(self.url, self.model)
        return f"{msg} {gpu}".strip()


class _ThinkUnsupported(Exception):
    pass


class _RepeatLoop(Exception):
    pass


# ---------------------------------------------------------------------- #
# Tiện ích cho trang Cài đặt
# ---------------------------------------------------------------------- #

async def ollama_status(url: str = "") -> dict:
    """{running, version, models:[{name,size_gb}], loaded:[...]}"""
    base = _base(url)
    out = {"url": base, "running": False, "version": None, "models": [], "loaded": [],
           "recommended": RECOMMENDED}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as c:
            v = await c.get(f"{base}/api/version")
            out["version"] = v.json().get("version")
            tags = (await c.get(f"{base}/api/tags")).json()
            out["models"] = [{"name": m.get("name"), "size_gb": round((m.get("size") or 0) / 1e9, 1)}
                             for m in tags.get("models", [])]
            ps = (await c.get(f"{base}/api/ps")).json()
            out["loaded"] = [{"name": m.get("name"), "size": m.get("size"), "size_vram": m.get("size_vram")}
                             for m in ps.get("models", [])]
            out["running"] = True
    except Exception:
        pass
    return out


async def gpu_usage(url: str, model: str) -> str:
    st = await ollama_status(url)
    for m in st["loaded"]:
        if m["name"] in (model, f"{model}:latest") and m.get("size"):
            pct = round(100 * (m.get("size_vram") or 0) / m["size"])
            if pct >= 95:
                return "· Chạy 100% trên card đồ họa ✅"
            if pct <= 5:
                return "· ⚠️ Đang chạy bằng CPU (chậm) — kiểm tra driver NVIDIA."
            return f"· {pct}% trên card đồ họa, phần còn lại chạy CPU (hơi chậm)."
    return ""


async def pull_model(url: str, model: str) -> AsyncIterator[dict]:
    """Tải model, trả về tiến độ {status, percent} từng bước."""
    base = _base(url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=10.0)) as c:
            async with c.stream("POST", f"{base}/api/pull", json={"model": model, "stream": True}) as r:
                if r.status_code >= 400:
                    yield {"status": "error", "message": f"Ollama lỗi {r.status_code}: {(await r.aread())[:200]!r}"}
                    return
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("error"):
                        yield {"status": "error", "message": d["error"]}
                        return
                    total, done = d.get("total"), d.get("completed")
                    pct = round(100 * done / total, 1) if total and done else None
                    yield {"status": d.get("status", ""), "percent": pct}
        yield {"status": "success", "percent": 100}
    except (httpx.ConnectError, httpx.ConnectTimeout):
        yield {"status": "error", "message": str(_not_running(base))}
