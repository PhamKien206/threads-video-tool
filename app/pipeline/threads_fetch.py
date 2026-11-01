"""
threads_fetch.py — Lấy bài gốc (cả chuỗi 1/N cùng tác giả) và bình luận từ link Threads.

Dùng Playwright (Chromium headless): chặn bắt response GraphQL/JSON của trang + đọc các khối JSON
nhúng sẵn trong HTML. Nhận dạng mọi object "bài viết" (pk + user + caption) rồi phân loại bằng
reply_to_author / self_thread, nên không phụ thuộc vào cách Threads lồng dữ liệu. Chỉ đọc chữ trên DOM khi không bắt được dữ liệu JSON.
Hỗ trợ cả threads.net và threads.com.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
from typing import Any, Optional
from urllib.parse import urlparse

TIMEOUT_MS = 35_000
SCROLLS = 6
SCROLL_DELAY = 1.3
HOSTS = {"threads.net", "threads.com"}
MAX_MEDIA = 4                 # số ảnh tối đa lấy cho mỗi bài/bình luận
MEDIA_MAX_BYTES = 15 * 1024 * 1024
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

BLOCKED_HINT = "Gợi ý: chụp màn hình bài viết và dùng cách \"Upload ảnh\"."


class ThreadsFetchError(RuntimeError):
    pass


_URL_IN_TEXT = re.compile(r"(?:https?://)?(?:www\.)?threads\.(?:net|com)/[^\s\"'<>]+", re.IGNORECASE)
_CODE = r"([A-Za-z0-9_-]+)"


def parse_threads_url(url: str) -> tuple[str, Optional[str]]:
    """Kiểm tra URL, trả về (url đã chuẩn hóa, mã bài).

    Nhận mọi dạng link Threads:
      - https://www.threads.com/@user/post/<mã>   (và threads.net)
      - https://www.threads.com/t/<mã>
      - https://www.threads.com/share/<mã>/       (link "Sao chép liên kết" trên app) → mã bài = None,
        mã thật được lấy sau khi trình duyệt mở link và chuyển hướng.
      - link có tham số thừa (?xmt=...&slof=1, ?igshid=...) hoặc dán kèm chữ thừa.
    """
    raw = (url or "").strip()
    if not raw:
        raise ThreadsFetchError("Bạn chưa dán link Threads.")
    m = _URL_IN_TEXT.search(raw)
    if not m:
        raise ThreadsFetchError("Link không phải của Threads. Bản này chỉ hỗ trợ link threads.net / threads.com.")
    url = m.group(0).rstrip(".,;)]}")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    if host not in HOSTS:
        raise ThreadsFetchError("Link không phải của Threads. Bản này chỉ hỗ trợ link threads.net / threads.com.")
    host = "threads.com"                     # threads.net chuyển hướng sang threads.com
    path = re.sub(r"/{2,}", "/", p.path).rstrip("/")

    m = re.search(r"/(@[^/]+)/post/" + _CODE, path)
    if m:
        return f"https://www.{host}/{m.group(1)}/post/{m.group(2)}", m.group(2)
    m = re.search(r"/post/" + _CODE, path)
    if m:
        return f"https://www.{host}{path}", m.group(1)
    m = re.match(r"^/t/" + _CODE + r"$", path)
    if m:
        return f"https://www.{host}/t/{m.group(1)}", m.group(1)
    m = re.match(r"^/share/" + _CODE + r"$", path)
    if m:
        # Mã trong link chia sẻ KHÔNG phải mã bài → để trình duyệt mở rồi đọc link thật.
        return f"https://www.{host}/share/{m.group(1)}/", None
    raise ThreadsFetchError(
        "Link chưa đúng dạng bài viết. Dùng link dạng threads.com/@ten/post/..., threads.com/t/... "
        "hoặc link chia sẻ threads.com/share/... (Mở bài → Chia sẻ → Sao chép liên kết).")


def code_from_url(url: str) -> Optional[str]:
    """Lấy mã bài từ link thật (sau khi chuyển hướng)."""
    m = re.search(r"/post/" + _CODE, urlparse(url or "").path) or re.search(r"^/t/" + _CODE, urlparse(url or "").path)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Bóc dữ liệu từ JSON
# ---------------------------------------------------------------------------

def _post_text(post: dict) -> str:
    cap = post.get("caption")
    if isinstance(cap, dict) and cap.get("text"):
        return str(cap["text"])
    info = post.get("text_post_app_info") or {}
    frags = ((info.get("text_fragments") or {}).get("fragments")) or []
    return "".join(str(f.get("plaintext", "")) for f in frags if isinstance(f, dict))


def _username(v) -> str:
    if isinstance(v, dict):
        return str(v.get("username") or "")
    return str(v or "")


def _media_urls(post: dict) -> list[dict]:
    """Ảnh của bài: ảnh đơn (image_versions2), nhiều ảnh (carousel_media), video → lấy ảnh bìa."""
    items = post.get("carousel_media") or [post]
    out: list[dict] = []
    for m in items:
        if not isinstance(m, dict):
            continue
        cands = [c for c in (((m.get("image_versions2") or {}).get("candidates")) or [])
                 if isinstance(c, dict) and c.get("url")]
        if not cands:
            continue
        best = max(cands, key=lambda c: int(c.get("width") or 0) * int(c.get("height") or 0))
        out.append({"url": best["url"], "width": int(best.get("width") or 0),
                    "height": int(best.get("height") or 0), "video": bool(m.get("video_versions"))})
    return out[:MAX_MEDIA]


def download_media(url: str, timeout: float = 30) -> bytes:
    """Tải một ảnh từ CDN của Threads (link đã ký sẵn, không cần đăng nhập)."""
    import httpx
    r = httpx.get(url, headers={"User-Agent": UA, "Referer": "https://www.threads.com/"},
                  timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    if len(r.content) > MEDIA_MAX_BYTES:
        raise ValueError("ảnh quá lớn")
    return r.content


def _norm_post(post: dict, path: str) -> Optional[dict]:
    pk = str(post.get("pk") or "")
    if not pk:
        return None
    info = post.get("text_post_app_info") or {}
    return {
        "pk": pk,
        "code": post.get("code") or "",
        "text": _post_text(post).strip(),
        "media": _media_urls(post),
        "username": _username(post.get("user")),
        "likes": int(post.get("like_count") or 0),
        "replies": int(info.get("direct_reply_count") or 0),
        "time": post.get("taken_at") or "",
        "is_reply": bool(info.get("is_reply")),
        "reply_to": _username(info.get("reply_to_author")),
        "self_thread": "self_thread" in path,
        "related": "relatedPosts" in path,
        "order": _edge_index(path) if "self_thread" in path else 10**6,
    }


def _edge_index(path: str) -> int:
    m = re.search(r"self_thread.*?/(\d+)(?:/|$)", path)
    return int(m.group(1)) if m else 10**6


def extract_posts(blob: Any) -> list[dict]:
    """Tìm mọi object 'bài viết' (có pk, user và caption/text_post_app_info) trong JSON, kèm ngữ cảnh đường dẫn."""
    found: list[dict] = []
    stack: list[tuple[Any, str]] = [(blob, "")]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            if "pk" in node and isinstance(node.get("user"), dict) and (
                    "caption" in node or "text_post_app_info" in node):
                p = _norm_post(node, path)
                if p:
                    found.append(p)
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    stack.append((v, f"{path}/{k}"[-200:]))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, (dict, list)):
                    stack.append((v, f"{path}/{i}"[-200:]))
    return found


def assemble(posts: list[dict], code: Optional[str]) -> dict:
    """Từ danh sách bài → bài gốc (+ các phần nối tiếp của cùng tác giả) và bình luận cấp 1."""
    by_pk: dict[str, dict] = {}
    for p in posts:
        old = by_pk.get(p["pk"])
        if old is None:
            by_pk[p["pk"]] = dict(p)
            continue
        if not old["text"] and p["text"]:
            old["text"] = p["text"]
        if not old["media"] and p["media"]:
            old["media"] = p["media"]
        if p["self_thread"]:
            old["self_thread"] = True
            old["order"] = min(old["order"], p["order"])
        old["related"] = old["related"] and p["related"]

    main = next((p for p in by_pk.values() if code and p["code"] == code), None)
    if main is None:
        main = next((p for p in by_pk.values() if not p["is_reply"] and not p["related"]), None)
    if main is None:
        return {"post": None, "comments": []}
    author = main["username"]

    def _order(p: dict) -> tuple:
        return (p["order"], int(p["pk"]) if p["pk"].isdigit() else 0)  # thứ tự hiển thị trong chuỗi

    chain = sorted((p for p in by_pk.values()
                    if p["pk"] != main["pk"] and p["username"] == author and p["self_thread"] and (p["text"] or p["media"])),
                   key=_order)
    parts = [main] + chain
    part_pks = {p["pk"] for p in parts}

    comments = [p for p in by_pk.values()
                if p["pk"] not in part_pks and p["is_reply"] and p["username"] != author
                and p["reply_to"] in ("", author) and not p["related"] and p["text"]]
    return {
        "post": {"author": author, "time": main["time"], "likes": main["likes"], "replies": main["replies"],
                 "parts": [{"text": p["text"], "pk": p["pk"], "media": p["media"]}
                           for p in parts if p["text"] or p["media"]]},
        "comments": [{"id": c["pk"], "text": c["text"], "username": c["username"], "likes": c["likes"],
                      "replies": c["replies"], "time": c["time"], "media": c["media"]} for c in comments],
    }


def _loads_lenient(text: str) -> Any:
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[9:]
    return json.loads(text)


# ---------------------------------------------------------------------------
# Playwright
# ---------------------------------------------------------------------------

def _parse_cookie(cookie: str, host: str) -> list[dict]:
    out = []
    for part in (cookie or "").split(";"):
        if "=" in part:
            name, _, value = part.strip().partition("=")
            if name.strip():
                out.append({"name": name.strip(), "value": value.strip(),
                            "domain": "." + host, "path": "/", "secure": True})
    return out


async def _fetch_async(url: str, code: Optional[str], cookie: str) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ThreadsFetchError(
            "Chưa cài Playwright. Chạy: pip install playwright rồi playwright install chromium"
        ) from exc

    blobs: list[Any] = []
    host = urlparse(url).netloc.removeprefix("www.")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=True)
        except Exception as exc:
            raise ThreadsFetchError(
                "Không mở được trình duyệt Chromium của Playwright. "
                "Chạy lệnh: playwright install chromium   (Linux thêm: playwright install-deps chromium)"
            ) from exc
        try:
            ctx = await browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 1600}, locale="vi-VN",
            )
            if cookie.strip():
                await ctx.add_cookies(_parse_cookie(cookie, host))
            page = await ctx.new_page()
            pending: list[asyncio.Task] = []

            async def _grab(resp):
                try:
                    if resp.request.resource_type not in ("xhr", "fetch"):
                        return
                    if "graphql" not in resp.url and "/api/" not in resp.url:
                        return
                    blobs.append(_loads_lenient(await resp.text()))
                except Exception:
                    pass

            page.on("response", lambda r: pending.append(asyncio.ensure_future(_grab(r))))

            try:
                resp = await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            except Exception as exc:
                raise ThreadsFetchError(f"Không tải được trang Threads (mạng chậm hoặc bị chặn). {BLOCKED_HINT}") from exc
            if resp is not None and resp.status in (404, 410):
                raise ThreadsFetchError("Bài viết không tồn tại hoặc đã bị xóa.")
            if "/login" in page.url or "accounts/login" in page.url:
                raise ThreadsFetchError(
                    "Threads yêu cầu đăng nhập để xem bài này. Nhập cookie trong Cài đặt (có rủi ro) "
                    f"hoặc dùng ảnh chụp. {BLOCKED_HINT}")
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            if code is None:  # link /share/ → đọc mã bài từ link thật sau chuyển hướng
                code = code_from_url(page.url)
                if code is None:
                    for sel, attr in (('link[rel="canonical"]', "href"), ('meta[property="og:url"]', "content")):
                        try:
                            real = await page.get_attribute(sel, attr, timeout=2000)
                        except Exception:
                            real = None
                        code = code_from_url(real or "")
                        if code:
                            break
                if code is None and "/share/" in page.url:
                    raise ThreadsFetchError(
                        "Không mở được link chia sẻ. Hãy mở bài trên trình duyệt rồi copy link từ thanh địa chỉ "
                        f"(dạng threads.com/@ten/post/...). {BLOCKED_HINT}")

            for _ in range(SCROLLS):
                await page.mouse.wheel(0, 2200)
                await asyncio.sleep(SCROLL_DELAY)

            # JSON nhúng sẵn trong trang
            for txt in await page.eval_on_selector_all(
                    'script[type="application/json"]', "els => els.map(e => e.textContent)"):
                if txt and '"pk"' in txt and ("caption" in txt or "text_post_app_info" in txt):
                    try:
                        blobs.append(json.loads(txt))
                    except json.JSONDecodeError:
                        pass
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            posts: list[dict] = []
            for b in blobs:
                posts.extend(extract_posts(b))
            data = assemble(posts, code)

            if not data["post"] or not data["post"]["parts"]:
                data = await _dom_fallback(page)
            return data
        finally:
            await browser.close()


async def _dom_fallback(page) -> dict:
    """Dự phòng: đọc chữ trên giao diện khi không bắt được JSON (không có số like, kém chính xác)."""
    texts = await page.eval_on_selector_all(
        'div[data-pressable-container="true"]',
        """els => els.map(e => {
             const spans = [...e.querySelectorAll('span[dir="auto"]')].map(s => s.innerText.trim());
             return spans.sort((a, b) => b.length - a.length)[0] || '';
           })""")
    texts = [t for t in texts if t and len(t) > 3]
    if not texts:
        return {"post": None, "comments": []}
    return {
        "post": {"author": "", "time": "", "likes": 0, "replies": 0, "parts": [{"text": texts[0], "pk": "dom0"}]},
        "comments": [{"id": f"dom{i}", "text": t, "username": f"u{i}", "likes": 0, "replies": 0, "time": ""}
                     for i, t in enumerate(texts[1:], start=1)],
    }


def _run_in_thread(coro_factory):
    """Chạy Playwright trong luồng riêng với event loop riêng (Windows cần ProactorEventLoop)."""
    result: dict = {}

    def _target():
        loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()  # type: ignore[attr-defined]
        try:
            result["value"] = loop.run_until_complete(coro_factory())
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            loop.close()

    th = threading.Thread(target=_target, daemon=True)
    th.start()
    th.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


async def fetch_thread(url: str, cookie: str = "") -> dict:
    """Lấy bài + bình luận. Lỗi → ThreadsFetchError (thông điệp tiếng Việt)."""
    norm_url, code = parse_threads_url(url)
    try:
        data = await asyncio.to_thread(_run_in_thread, lambda: _fetch_async(norm_url, code, cookie or ""))
    except ThreadsFetchError:
        raise
    except Exception as exc:
        raise ThreadsFetchError(f"Lỗi khi lấy dữ liệu Threads: {exc}. {BLOCKED_HINT}") from exc
    if not data.get("post") or not data["post"].get("parts"):
        raise ThreadsFetchError(
            "Không đọc được nội dung bài viết (Threads có thể đang chặn truy cập tự động "
            f"hoặc bài ở chế độ riêng tư). {BLOCKED_HINT}")
    return data
