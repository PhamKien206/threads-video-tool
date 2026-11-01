"""
textnorm.py — Chuẩn hóa chữ tiếng Việt cho giọng đọc + tách câu.

Dùng làm lưới an toàn sau khi AI tạo speak_text (đảm bảo không đọc "*", "1/7", emoji, số dạng chữ số)
và làm planner dự phòng khi chưa có API key.
"""
from __future__ import annotations

import re

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_GROUPS = ["", "nghìn", "triệu", "tỷ"]


def _read_triple(n: int, full: bool) -> str:
    h, t, u = n // 100, (n // 10) % 10, n % 10
    parts: list[str] = []
    if full or h:
        parts += [_DIGITS[h], "trăm"]
    if t == 0:
        if u and parts:
            parts.append("lẻ")
        if u:
            parts.append(_DIGITS[u])
    elif t == 1:
        parts.append("mười")
        if u == 5:
            parts.append("lăm")
        elif u:
            parts.append(_DIGITS[u])
    else:
        parts += [_DIGITS[t], "mươi"]
        if u == 1:
            parts.append("mốt")
        elif u == 4:
            parts.append("tư")
        elif u == 5:
            parts.append("lăm")
        elif u:
            parts.append(_DIGITS[u])
    return " ".join(parts)


def read_number(n: int) -> str:
    """Đọc số nguyên thành chữ: 1250 → 'một nghìn hai trăm năm mươi'."""
    if n < 0:
        return "âm " + read_number(-n)
    if n == 0:
        return "không"
    if n >= 10**12:
        return " ".join(_DIGITS[int(d)] for d in str(n))
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    words: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        full = i < len(groups) - 1  # nhóm không đứng đầu thì đọc đủ "không trăm"
        words.append(_read_triple(g, full))
        if _GROUPS[i]:
            words.append(_GROUPS[i])
    return " ".join(words)


def _read_digits_str(s: str) -> str:
    s = s.lstrip("0") or "0"
    return read_number(int(s))


# ---------------------------------------------------------------------------
# Chuẩn hóa
# ---------------------------------------------------------------------------

_RE_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "‍️←-⇿⬀-⯿⌀-⏿]+"
)
_RE_BULLET = re.compile(r"^\s*(?:[*•\-–—+>·]+|\d{1,2}[.)])\s+", re.MULTILINE)
# số thứ tự kiểu "1/7": chỉ khi đứng riêng một dòng hoặc ở cuối đoạn ("1/2 số tiền" vẫn được đọc)
_RE_PART = re.compile(r"(?m)^\s*\(?\d{1,2}\s*/\s*\d{1,2}\)?\s*$|\s\(?\d{1,2}/\d{1,2}\)?\s*\Z")

_ABBR = {
    "ko": "không", "k": "không", "kh": "không", "khum": "không",
    "dc": "được", "đc": "được", "ng": "người", "vs": "với", "mn": "mọi người",
    "bt": "bình thường", "j": "gì", "z": "vậy", "r": "rồi", "ntn": "như thế nào",
    "cx": "cũng", "trc": "trước", "nch": "nói chung", "lm": "làm", "ns": "nói",
    "cmt": "bình luận", "cmts": "bình luận", "rep": "trả lời", "ib": "nhắn tin", "fb": "phây búc",
    "ae": "anh em", "ny": "người yêu", "ck": "chồng", "vk": "vợ", "bn": "bạn", "mk": "mình",
    "cmn": "con mẹ nó", "vcl": "vãi", "vl": "vãi", "đm": "", "dm": "", "wtf": "trời ơi",
}
_UNITS = {
    "%": "phần trăm", "k": "nghìn", "tr": "triệu", "củ": "triệu",
    "đ": "đồng", "vnđ": "đồng", "vnd": "đồng", "kg": "ki lô gam", "km": "ki lô mét",
    "h": "giờ", "m": "mét", "cm": "xen ti mét", "tỷ": "tỷ", "triệu": "triệu",
}


def _number_token(m: re.Match) -> str:
    raw, unit = m.group(1), (m.group(2) or "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):          # 1.000.000
        words = _read_digits_str(raw.replace(".", ""))
    elif re.fullmatch(r"\d+[.,]\d+", raw):                  # 1,5 hoặc 1.5
        a, b = re.split(r"[.,]", raw)
        words = f"{_read_digits_str(a)} phẩy {' '.join(_DIGITS[int(d)] for d in b) if len(b) > 2 else _read_digits_str(b)}"
    else:
        words = _read_digits_str(raw)
    u = unit.lower()
    if u:
        words += " " + _UNITS.get(u, unit)
    return f" {words} "


_RE_NUMBER = re.compile(r"(?<![\w])(\d{1,3}(?:\.\d{3})+|\d+[.,]\d+|\d+)\s?(%|k|tr|củ|vnđ|vnd|đ|kg|km|cm|h|m)?(?![\w])", re.IGNORECASE)
_RE_NUMBER_LOOSE = re.compile(r"\d+")


def normalize_speak_text(text: str) -> str:
    """Chuyển văn bản hiển thị thành văn bản để máy đọc."""
    s = text or ""
    s = _RE_BULLET.sub("", s)
    s = _RE_PART.sub(" ", s)
    s = _RE_EMOJI.sub(" ", s)
    s = re.sub(r"https?://\S+", " ", s)
    s = s.replace("*", " ").replace("#", " ").replace("_", " ").replace("~", " ")
    s = re.sub(r"[\"“”«»„]", "", s)
    s = re.sub(r"(?<!\w)['‘’]|['‘’](?!\w)", "", s)
    s = re.sub(r"\s*[(\[]\s*", ", ", s)
    s = re.sub(r"\s*[)\]]\s*", ", ", s)
    s = re.sub(r"(\d)\s*-\s*(\d)", r"\1 đến \2", s)
    s = re.sub(r"(\d)\s*/\s*(\d)", r"\1 phần \2", s)
    s = re.sub(r"(?<=\w)\s*/\s*(ngày|tháng|năm|tuần|giờ|phút|người|lần|tháng|kg|km)\b", r" một \1", s)
    s = re.sub(r"(?<=\w)\s*/\s*(?=\w)", " hoặc ", s)
    s = re.sub(r"\s+[-–—]+\s+", ", ", s)
    s = s.replace("&", " và ").replace("+", " cộng ").replace("=", " bằng ")
    s = _RE_NUMBER.sub(_number_token, s)
    s = _RE_NUMBER_LOOSE.sub(lambda m: f" {_read_digits_str(m.group(0))} ", s)

    def _abbr(m: re.Match) -> str:
        w = m.group(0)
        rep = _ABBR.get(w.lower())
        return rep if rep else w

    s = re.sub(r"(?<![\w])[A-Za-zđĐ]{1,4}(?![\w])", _abbr, s)
    s = s.replace("\n", ". ")
    s = re.sub(r"\s+([,.!?:;])", r"\1", s)
    s = re.sub(r"([,.!?:;])(?:\s*[,])+", r"\1", s)
    s = re.sub(r"^[\s,.;:]+", "", s)
    s = re.sub(r"\.{2,}|…", ".", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = re.sub(r"[,;:\s]+$", "", s)
    if s and s[-1] not in ".!?":
        s += "."
    return s


def has_speakable(text: str) -> bool:
    return bool(re.search(r"\w", text or ""))


# ---------------------------------------------------------------------------
# Tách câu
# ---------------------------------------------------------------------------

def split_sentences(body: str, min_words: int = 6, max_words: int = 30) -> list[str]:
    """Tách thân bài thành các câu đọc tự nhiên (6–30 từ)."""
    raw: list[str] = []
    for line in (body or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=[.!?…:])\s+(?=\S)", line)
        raw.extend(p.strip() for p in parts if p.strip())

    # tách câu quá dài ở dấu phẩy
    pieces: list[str] = []
    for sent in raw:
        if len(sent.split()) <= max_words:
            pieces.append(sent)
            continue
        chunk: list[str] = []
        for clause in re.split(r"(?<=[,;])\s+", sent):
            if chunk and len(" ".join(chunk + [clause]).split()) > max_words:
                pieces.append(" ".join(chunk))
                chunk = []
            chunk.append(clause)
        if chunk:
            pieces.append(" ".join(chunk))

    # gộp câu quá ngắn vào câu trước (nếu vừa), không thì vào câu sau
    merged: list[str] = []
    carry = ""
    for p in pieces:
        if carry:
            p = f"{carry} {p}"
            carry = ""
        n = len(p.split())
        if n >= min_words:
            merged.append(p)
        elif merged and len((merged[-1] + " " + p).split()) <= max_words:
            merged[-1] = f"{merged[-1]} {p}"
        else:
            carry = p
    if carry:
        if merged and len((merged[-1] + " " + carry).split()) <= max_words + 8:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged


# ---------------------------------------------------------------------------
# Làm sạch lần cuối ngay trước khi gửi cho máy đọc (áp dụng cho MỌI câu,
# kể cả câu do AI viết hoặc người dùng tự sửa) → tránh lỗi "No audio was received".
# ---------------------------------------------------------------------------
import unicodedata as _ud

_ALLOWED_PUNCT = set(".,!?;:'-")


def clean_for_tts(text: str) -> str:
    """Bỏ mọi ký tự đặc biệt, chỉ giữ chữ, số, khoảng trắng và dấu câu cơ bản."""
    s = _ud.normalize("NFC", text or "")
    s = re.sub(r"<[^>]{0,80}>", " ", s)               # thẻ HTML <b>, <br>...
    s = re.sub(r"&(?:nbsp|amp|lt|gt|quot|#\d+);", " ", s)
    s = re.sub(r"([,.!?;:])(?=[^\W\d_])", r"\1 ", s)   # "Topic:Một" → "Topic: Một"
    s = normalize_speak_text(s)                      # emoji, số, viết tắt, ngoặc, gạch đầu dòng...
    out = []
    for ch in s:
        cat = _ud.category(ch)
        if ch.isalnum() or ch in _ALLOWED_PUNCT:
            out.append(ch)
        elif ch.isspace() or cat.startswith(("Z", "C")):   # khoảng trắng lạ, ký tự ẩn/điều khiển
            out.append(" ")
        elif cat.startswith("M"):                     # dấu kết hợp lẻ
            continue
        else:                                         # ký hiệu, emoji, ngoặc, < > & @ $ ...
            out.append(" ")
    s = "".join(out)
    s = re.sub(r"(?<!\w)['-]|['-](?!\w)", " ", s)    # nháy/gạch đứng lẻ
    s = re.sub(r"([.,!?;:])\1+", r"\1", s)            # ",,," → ","
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    s = re.sub(r"[,;:]\s*([.!?])", r"\1", s)
    s = re.sub(r"^[\s,.;:!?]+", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    if s and s[-1] not in ".!?":
        s = s.rstrip(",;:") + "."
    return s
