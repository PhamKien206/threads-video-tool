"""
card_render.py — Tự vẽ thẻ kiểu Threads bằng Pillow (dùng cho nguồn link Threads).

Nền trắng, góc vuông, padding 28 px, font Be Vietnam Pro 34 px.
Header: avatar tròn, tên, "· thời gian" màu xám. Bình luận: đường kẻ dọc xám bên trái,
tên hiển thị "Người dùng N", avatar xám trơn.
"""
from __future__ import annotations

import hashlib
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from app.config import FONTS_DIR

CARD_W = 920
PADDING = 28
BODY_SIZE = 34
NAME_SIZE = 30
META_SIZE = 26
AVATAR = 64
LINE_SPACING = 12
TEXT = (16, 16, 16)
GRAY = (153, 153, 153)
LINE_GRAY = (210, 210, 210)
AVATAR_GRAY = (200, 200, 200)
WHITE = (255, 255, 255)

_FONT_FILES = {
    False: ["BeVietnamPro-Regular.ttf"],
    True: ["BeVietnamPro-SemiBold.ttf", "BeVietnamPro-Bold.ttf", "BeVietnamPro-Medium.ttf"],
}
_SYSTEM_FALLBACK = {
    False: ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    True: ["DejaVuSans-Bold.ttf", "arialbd.ttf", "segoeuib.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


@lru_cache(maxsize=32)
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Font Be Vietnam Pro (app/fonts/), nếu thiếu thì dùng font hệ thống có hỗ trợ tiếng Việt."""
    for name in _FONT_FILES[bold] + _FONT_FILES[False]:
        p = FONTS_DIR / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                pass
    for name in _SYSTEM_FALLBACK[bold] + _SYSTEM_FALLBACK[False]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


_RE_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF‍️]+")


def _clean_for_font(text: str) -> str:
    """Font chữ không có emoji → bỏ để không hiện ô vuông."""
    return re.sub(r"[ \t]{2,}", " ", _RE_EMOJI.sub("", text or "")).strip()


def _text_w(font: ImageFont.FreeTypeFont, s: str) -> int:
    return int(font.getlength(s))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if _text_w(font, cand) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            while _text_w(font, w) > max_w:  # từ quá dài (link...) → bẻ
                cut = len(w)
                while cut > 1 and _text_w(font, w[:cut]) > max_w:
                    cut -= 1
                lines.append(w[:cut])
                w = w[cut:]
            cur = w
        lines.append(cur)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def relative_time(ts) -> str:
    """unix timestamp → '3 giờ', '2 ngày'..."""
    try:
        diff = max(0, time.time() - float(ts))
    except (TypeError, ValueError):
        return str(ts or "").strip()
    for unit, sec in (("năm", 31536000), ("tuần", 604800), ("ngày", 86400), ("giờ", 3600), ("phút", 60)):
        if diff >= sec:
            return f"{int(diff // sec)} {unit}"
    return "vừa xong"


def _avatar(name: str, gray: bool) -> Image.Image:
    size = AVATAR * 2  # vẽ 2x rồi thu nhỏ cho mịn
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if gray:
        d.ellipse([0, 0, size - 1, size - 1], fill=AVATAR_GRAY)
    else:
        h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
        palettes = [((255, 110, 90), (255, 190, 70)), ((80, 140, 255), (160, 90, 255)),
                    ((40, 190, 150), (90, 210, 255)), ((255, 80, 150), (255, 160, 90))]
        c1, c2 = palettes[h % len(palettes)]
        for y in range(size):
            r = y / size
            col = tuple(int(c1[i] * (1 - r) + c2[i] * r) for i in range(3))
            d.line([(0, y), (size, y)], fill=col)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        img.putalpha(mask)
        initial = (name.strip()[:1] or "?").upper()
        f = load_font(size // 2, bold=True)
        l, t, r, b = f.getbbox(initial)
        d.text(((size - (r - l)) / 2 - l, (size - (b - t)) / 2 - t), initial, font=f, fill=(255, 255, 255))
    return img.resize((AVATAR, AVATAR), Image.LANCZOS)


MEDIA_GAP = 8          # khe giữa các ảnh
MEDIA_RADIUS = 18
MEDIA_MAX_H = 720      # ảnh cao hơn thì thu nhỏ (giữ tỉ lệ, canh trái như Threads)
MEDIA_MIN_H = 280
CARD_MAX_H = 1120      # = timeline.CARD_MAX_H: thẻ cao hơn sẽ bị thu nhỏ cả thẻ trên video


def _open_media(paths: list) -> list[Image.Image]:
    out = []
    for p in paths or []:
        try:
            with Image.open(p) as im:
                out.append(im.convert("RGB"))
        except Exception:
            continue
    return out


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """Cắt giữa cho lấp đầy ô w×h (kiểu object-fit: cover)."""
    scale = max(w / im.width, h / im.height)
    nw, nh = max(w, round(im.width * scale)), max(h, round(im.height * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return im.crop((left, top, left + w, top + h))


def _rounded(im: Image.Image) -> tuple[Image.Image, Image.Image]:  # (ảnh, mask bo góc)
    scale = 3  # vẽ mask lớn rồi thu nhỏ cho góc mịn
    big = Image.new("L", (im.width * scale, im.height * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle([0, 0, big.width - 1, big.height - 1],
                                          radius=MEDIA_RADIUS * scale, fill=255)
    return im, big.resize(im.size, Image.LANCZOS)


def _media_tiles(images: list[Image.Image], max_w: int, max_h: int) -> list[tuple[Image.Image, int, int]]:
    """Xếp ảnh: trả về [(ảnh đã co, x, y)] trong khung rộng max_w."""
    n = len(images)
    if n == 1:
        im = images[0]
        w = max_w
        h = round(im.height * w / max(im.width, 1))
        if h > max_h:
            h = max_h
            w = round(im.width * h / max(im.height, 1))
        return [(im.resize((max(w, 1), max(h, 1)), Image.LANCZOS), 0, 0)]
    if n in (2, 3):
        cw = (max_w - MEDIA_GAP * (n - 1)) // n
        ch = min(max_h, round(cw * (1.25 if n == 2 else 1.35)))
        return [(_cover(im, cw, ch), i * (cw + MEDIA_GAP), 0) for i, im in enumerate(images)]
    cw = (max_w - MEDIA_GAP) // 2
    ch = min((max_h - MEDIA_GAP) // 2, round(cw * 0.8))
    return [(_cover(im, cw, ch), (i % 2) * (cw + MEDIA_GAP), (i // 2) * (ch + MEDIA_GAP))
            for i, im in enumerate(images[:4])]


def render_card_image(card: dict, output_path: str | Path) -> str:
    """Vẽ một thẻ.

    card: {body, kind: post|comment, display_name, time, likes, replies, part_index, part_total, gray_avatar,
           media: [đường dẫn ảnh đính kèm]}
    """
    kind = card.get("kind", "post")
    name = card.get("display_name") or ("Người dùng" if kind == "comment" else "Tác giả")
    gray_avatar = bool(card.get("gray_avatar", kind == "comment"))
    when = card.get("time") or ""
    body = _clean_for_font(card.get("body", ""))

    f_body = load_font(BODY_SIZE)
    f_name = load_font(NAME_SIZE, bold=True)
    f_meta = load_font(META_SIZE)

    text_x = PADDING + AVATAR + 18
    text_w = CARD_W - text_x - PADDING
    lines = wrap_text(body, f_body, text_w)
    line_h = BODY_SIZE + LINE_SPACING

    stats = []
    if card.get("likes"):
        stats.append(f"{card['likes']} lượt thích")
    if card.get("replies"):
        stats.append(f"{card['replies']} trả lời")
    footer_h = (META_SIZE + 18) if stats else 0

    header_h = AVATAR
    name_block_h = NAME_SIZE + 12
    images = _open_media(card.get("media") or [])
    body_h = (max(1, len(lines)) if lines or not images else 0) * line_h

    tiles: list[tuple[Image.Image, int, int]] = []
    media_h = 0
    if images:
        room = CARD_MAX_H - (PADDING * 2 + name_block_h + body_h + footer_h + 16)
        tiles = _media_tiles(images, text_w, max(MEDIA_MIN_H, min(MEDIA_MAX_H, room)))
        media_h = max(y + t.height for t, _, y in tiles) + (16 if lines else 4)
    extra = len(images) - len(tiles)

    height = PADDING + max(header_h, name_block_h + body_h + media_h + footer_h) + PADDING
    height = max(height, PADDING * 2 + AVATAR)

    img = Image.new("RGB", (CARD_W, int(height)), WHITE)
    d = ImageDraw.Draw(img)

    av = _avatar(name, gray_avatar)
    img.paste(av, (PADDING, PADDING), av)

    if kind == "comment":  # đường kẻ dọc dưới avatar (kiểu trả lời của Threads)
        lx = PADDING + AVATAR // 2
        d.line([(lx, PADDING + AVATAR + 10), (lx, height - PADDING)], fill=LINE_GRAY, width=4)

    # Tên + thời gian
    y = PADDING
    d.text((text_x, y), name, font=f_name, fill=TEXT)
    nx = text_x + _text_w(f_name, name) + 10
    if when:
        d.text((nx, y + (NAME_SIZE - META_SIZE) // 2 + 2), f"· {when}", font=f_meta, fill=GRAY)
    if card.get("part_index") and card.get("part_total"):
        label = f"{card['part_index']}/{card['part_total']}"
        d.text((CARD_W - PADDING - _text_w(f_meta, label), y + 4), label, font=f_meta, fill=GRAY)

    # Thân bài
    y += name_block_h
    for line in lines:
        d.text((text_x, y), line, font=f_body, fill=TEXT)
        y += line_h

    if tiles:
        y += 16 if lines else 4
        for i, (t, tx, ty) in enumerate(tiles):
            more = extra > 0 and i == len(tiles) - 1          # còn ảnh chưa hiện → ô cuối tối đi + "+N"
            if more:
                t = Image.blend(t, Image.new("RGB", t.size, (0, 0, 0)), 0.45)
            t, mask = _rounded(t)
            img.paste(t, (text_x + tx, y + ty), mask)
            d.rounded_rectangle([text_x + tx, y + ty, text_x + tx + t.width - 1, y + ty + t.height - 1],
                                radius=MEDIA_RADIUS, outline=LINE_GRAY, width=1)
            if more:
                f_more = load_font(56, bold=True)
                label = f"+{extra}"
                d.text((text_x + tx + (t.width - _text_w(f_more, label)) // 2, y + ty + (t.height - 56) // 2 - 8),
                       label, font=f_more, fill=WHITE)
        y += media_h - (16 if lines else 4)

    if stats:
        d.text((text_x, y + 6), "   ·   ".join(stats), font=f_meta, fill=GRAY)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return str(output_path)


def render_transition_card(text: str, output_path: str | Path) -> str:
    """Thẻ câu chuyển cảnh ("Và đây là bình luận của cư dân mạng:")."""
    f = load_font(BODY_SIZE + 4, bold=True)
    lines = wrap_text(_clean_for_font(text), f, CARD_W - PADDING * 2)
    line_h = BODY_SIZE + 4 + LINE_SPACING
    height = PADDING * 2 + 8 + len(lines) * line_h
    img = Image.new("RGB", (CARD_W, height), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 8, height], fill=(17, 17, 17))
    y = PADDING + 4
    for line in lines:
        d.text(((CARD_W - _text_w(f, line)) // 2, y), line, font=f, fill=TEXT)
        y += line_h
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return str(output_path)


def display_time(ts: Optional[object]) -> str:
    return relative_time(ts) if ts not in (None, "") else ""
