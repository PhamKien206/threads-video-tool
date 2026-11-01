"""
timeline.py — Tính mốc thời gian và bố cục cho từng câu, từng thẻ, từng meme.

Luật:
- Nghỉ 0,3 s giữa các câu trong một thẻ, 0,5 s giữa các thẻ.
- Thẻ xuất hiện đúng lúc bắt đầu đọc câu đầu tiên của nó (fade + trượt lên 40 px trong 0,25 s).
- Tối đa 2 thẻ cùng lúc: thẻ mới nằm dưới thẻ cũ (cách 24 px); thẻ thứ 3 vào thì thẻ đầu trượt lên
  và mờ dần, thẻ thứ hai dời lên vị trí trên cùng. Thiếu chỗ thì chỉ giữ thẻ mới.
- Câu chuyển cảnh trước phần bình luận là một thẻ riêng và dọn sạch các thẻ bài gốc.
- Meme hiện ở đầu câu được gán, kéo dài max(1,5; min(2,5; độ dài câu)) giây, đặt dưới thẻ cuối 40 px;
  thiếu chỗ thì đặt ở 1/3 dưới màn hình.
- Tổng dài hơn max_duration → chia Part theo ranh giới thẻ.
"""
from __future__ import annotations

from typing import Any

VIDEO_W, VIDEO_H = 1080, 1920
CARD_W = 920
CARD_TOP = 260
CARD_GAP = 24
STACK_MAX_BOTTOM = 1380          # chừa chỗ cho meme ở dưới
CARD_MAX_H = STACK_MAX_BOTTOM - CARD_TOP
ANIM = 0.25                      # thời gian hiệu ứng vào/ra/dời thẻ
ENTER_OFFSET = 40                # trượt lên 40 px khi vào
EXIT_OFFSET = 80                 # trượt lên khi bị đẩy ra
MEME_H = 420
MEME_MARGIN = 40
MEME_BOUNCE_MAX = 1.1
SAFE_BOTTOM = VIDEO_H - 80

SENTENCE_GAP = 0.3
CARD_GAP_TIME = 0.5
TAIL = 0.6                       # để video không bị cắt ngay khi đọc xong câu cuối
MEME_MIN, MEME_MAX = 1.5, 2.5

TRANSITION_ID = "transition"


def display_size(orig_w: int, orig_h: int) -> tuple[int, int]:
    """Kích thước thẻ trên video: rộng 920 px; quá cao thì thu nhỏ cho vừa."""
    w = CARD_W
    h = round(orig_h * CARD_W / max(orig_w, 1))
    if h > CARD_MAX_H:
        h = CARD_MAX_H
        w = round(orig_w * CARD_MAX_H / max(orig_h, 1))
    return int(w) // 2 * 2, int(h) // 2 * 2


def sequence_cards(plan: dict) -> list[dict]:
    """Danh sách thẻ theo thứ tự trình chiếu, chèn thẻ chuyển cảnh trước bình luận đầu tiên."""
    cards = [dict(c) for c in plan.get("cards", []) if c.get("sentences")]
    trans = (plan.get("transition_before_comments") or "").strip()
    if trans:
        idx = next((i for i, c in enumerate(cards) if c.get("kind") == "comment"), None)
        if idx is not None and idx > 0:
            cards.insert(idx, {
                "card_id": TRANSITION_ID, "kind": "transition", "image": "cards/transition.png",
                "sentences": [{"id": TRANSITION_ID, "display_text": trans, "speak_text": trans, "meme": None}],
            })
    return cards


def _card_speech_len(card: dict, durations: dict[str, float]) -> float:
    ds = [durations[s["id"]] for s in card["sentences"]]
    return sum(ds) + SENTENCE_GAP * (len(ds) - 1)


def split_parts(cards: list[dict], durations: dict[str, float], max_duration: float) -> list[list[dict]]:
    """Chia thẻ thành các Part, mỗi Part ≤ max_duration (không cắt giữa thẻ)."""
    parts: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0.0
    for c in cards:
        clen = _card_speech_len(c, durations)
        add = clen + (CARD_GAP_TIME if cur else 0.0)
        if cur and cur_len + add + TAIL > max_duration:
            parts.append(cur)
            cur, cur_len = [], 0.0
            add = clen
        cur.append(c)
        cur_len += add
    if cur:
        parts.append(cur)
    # Thẻ chuyển cảnh không được nằm cuối một Part
    for i in range(len(parts) - 1):
        if parts[i] and parts[i][-1].get("kind") == "transition":
            parts[i + 1].insert(0, parts[i].pop())
    return [p for p in parts if p]


def _layout_part(cards: list[dict], audio: dict[str, tuple[str, float]],
                 card_sizes: dict[str, tuple[int, int]]) -> dict[str, Any]:
    durations = {k: v[1] for k, v in audio.items()}
    t = 0.0
    sentences_out: list[dict] = []
    cards_out: list[dict] = []
    memes_out: list[dict] = []
    stack: list[dict] = []

    for ci, card in enumerate(cards):
        if ci > 0:
            t += CARD_GAP_TIME - SENTENCE_GAP  # đã cộng SENTENCE_GAP sau câu cuối thẻ trước
        cid = card["card_id"]
        ow, oh = card_sizes[cid]
        w, h = display_size(ow, oh)
        entry = {
            "card_id": cid, "image": card["image"], "kind": card.get("kind", "post"),
            "w": w, "h": h, "x": (VIDEO_W - w) // 2,
            "start": round(t, 3), "end": None, "moves": [], "fade_out_at": None, "y": 0,
        }

        # --- Quyết định thẻ nào ở lại, thẻ nào bị đẩy ra
        if entry["kind"] == "transition":
            keep, exiting = [], stack
        else:
            keep, exiting = stack[-1:], stack[:-1]
            if keep and CARD_TOP + keep[0]["h"] + CARD_GAP + h > STACK_MAX_BOTTOM:
                exiting, keep = exiting + keep, []
        for e in exiting:
            e["moves"].append({"t": round(t, 3), "y0": e["y"], "y1": e["y"] - EXIT_OFFSET})
            e["fade_out_at"] = round(t, 3)
            e["end"] = round(t + ANIM, 3)
        y = CARD_TOP
        for k in keep:
            if k["y"] != y:
                k["moves"].append({"t": round(t, 3), "y0": k["y"], "y1": y})
                k["y"] = y
            y += k["h"] + CARD_GAP
        entry["y"] = y
        entry["moves"].append({"t": round(t, 3), "y0": y + ENTER_OFFSET, "y1": y})
        stack = keep + [entry]
        cards_out.append(entry)
        stack_bottom = max(c["y"] + c["h"] for c in stack)

        # --- Các câu của thẻ
        for s in card["sentences"]:
            sid = s["id"]
            wav, dur = audio[sid]
            start, end = t, t + dur
            sentences_out.append({"id": sid, "card_id": cid, "start": round(start, 3),
                                  "end": round(end, 3), "wav": wav})
            if s.get("meme"):
                my = stack_bottom + MEME_MARGIN
                if my + MEME_H * MEME_BOUNCE_MAX > SAFE_BOTTOM:
                    my = VIDEO_H * 2 // 3 + (VIDEO_H // 3 - MEME_H) // 2
                memes_out.append({
                    "sentence_id": sid, "file": s["meme"], "start": round(start, 3),
                    "end": round(start + max(MEME_MIN, min(MEME_MAX, dur)), 3), "y": int(my),
                })
            t = end + SENTENCE_GAP

    duration = round(t - SENTENCE_GAP + TAIL, 3)
    for c in cards_out:
        if c["end"] is None:
            c["end"] = duration
        c.pop("y", None)
    for m in memes_out:
        m["end"] = min(m["end"], duration)
    return {"duration": duration, "sentences": sentences_out, "cards": cards_out, "memes": memes_out}


def build_timeline(plan: dict, audio: dict[str, tuple[str, float]],
                   card_sizes: dict[str, tuple[int, int]], max_duration: float = 90) -> dict[str, Any]:
    """Tạo timeline cho toàn video.

    Args:
        plan: plan.json (cards → sentences)
        audio: {sentence_id: (wav_path, duration)} — gồm cả câu chuyển cảnh nếu có (id "transition")
        card_sizes: {card_id: (width, height)} kích thước gốc của ảnh thẻ
        max_duration: độ dài tối đa mỗi video (giây)

    Returns:
        {"parts": [{"index": 1|None, "duration", "sentences", "cards", "memes"}], "total_duration"}
    """
    cards = sequence_cards(plan)
    if not cards:
        raise ValueError("Kế hoạch không có câu nào để đọc.")
    missing = [s["id"] for c in cards for s in c["sentences"] if s["id"] not in audio]
    if missing:
        raise ValueError(f"Thiếu giọng đọc cho câu: {', '.join(missing[:5])}")
    durations = {k: v[1] for k, v in audio.items()}
    groups = split_parts(cards, durations, max(15.0, float(max_duration or 90)))
    parts = []
    for i, group in enumerate(groups, start=1):
        part = _layout_part(group, audio, card_sizes)
        part["index"] = i if len(groups) > 1 else None
        parts.append(part)
    return {"parts": parts, "total_duration": round(sum(p["duration"] for p in parts), 3)}
