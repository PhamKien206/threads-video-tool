"""
planner.py — AI chia câu, chuẩn hóa giọng đọc và chọn meme (prompt B2: app/prompts/planner.md).

Sau khi AI trả về, code kiểm tra lại: thẻ/câu hợp lệ, meme phải tồn tại, áp luật mật độ meme.
Sai thì tự sửa. Không có API key → planner dự phòng (tách câu bằng quy tắc, không chọn meme theo ngữ nghĩa).
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from app.config import media_dir
from app.llm.base import LLMBase
from app.pipeline.ocr import load_prompt
from app.pipeline.textnorm import has_speakable, normalize_speak_text, split_sentences

MAX_USES_PER_MEME = 2

# Mật độ: khoảng cách tối thiểu giữa 2 câu có meme (tính theo chỉ số câu) và tỉ lệ tối đa
DENSITY_RULES = {
    "ít":    {"min_gap": 3, "ratio": 1 / 4, "per_card": 1},
    "vừa":   {"min_gap": 2, "ratio": 1 / 2.5, "per_card": None},
    "nhiều": {"min_gap": 2, "ratio": 1 / 1.5, "per_card": None},
}


# ---------------------------------------------------------------------------
# Kiểm tra schema phản hồi AI
# ---------------------------------------------------------------------------

def _validator(card_ids: list[str]):
    def _v(data: Any) -> Optional[str]:
        if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
            return 'cần object có trường "cards" là danh sách'
        seen = set()
        for c in data["cards"]:
            if not isinstance(c, dict) or not isinstance(c.get("sentences"), list):
                return 'mỗi phần tử trong "cards" cần có "card_id" và "sentences" (danh sách)'
            cid = str(c.get("card_id", ""))
            if cid not in card_ids:
                return f'card_id "{cid}" không có trong đầu vào; chỉ dùng: {", ".join(card_ids)}'
            seen.add(cid)
            for s in c["sentences"]:
                if not isinstance(s, dict) or not str(s.get("display_text", "")).strip():
                    return f'thẻ {cid}: mỗi câu cần "display_text" không rỗng'
        missing = [cid for cid in card_ids if cid not in seen]
        if missing:
            return f'thiếu thẻ: {", ".join(missing)} — phải trả về đủ mọi thẻ'
        return None
    return _v


# ---------------------------------------------------------------------------
# Luật meme
# ---------------------------------------------------------------------------

def meme_name(value) -> str | None:
    """Tên file meme từ câu trả lời AI. Model nhỏ hay trả object ({"file": ...}) hoặc list thay vì chuỗi."""
    if isinstance(value, dict):
        value = next((value.get(k) for k in ("file", "name", "filename", "meme") if isinstance(value.get(k), str)), None)
    elif isinstance(value, list):
        value = next((v for v in value if isinstance(v, str)), None)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return None if value.lower() in ("", "none", "null", "không", "khong") else value


def meme_exists(meme_file) -> bool:
    meme_file = meme_name(meme_file)
    if not meme_file:
        return False
    base = media_dir("meme").resolve()
    p = (base / meme_file).resolve()
    return p.parent == base and p.is_file()


def enforce_meme_rules(plan: dict, density: str) -> dict:
    """Áp luật mật độ meme lên toàn video, sửa tại chỗ:
    - câu đầu tiên của video không có meme
    - không 2 câu liền nhau đều có meme (khoảng cách tối thiểu theo mật độ)
    - mỗi meme tối đa 2 lần / video
    - tổng số meme không vượt tỉ lệ của mật độ; 'ít' tối đa 1 meme / thẻ
    """
    rule = DENSITY_RULES.get(density, DENSITY_RULES["vừa"])
    flat = [(c, s) for c in plan.get("cards", []) for s in c.get("sentences", [])]

    usage: dict[str, int] = {}
    last_idx = -10**9
    per_card: dict[str, int] = {}
    for idx, (card, s) in enumerate(flat):
        meme = s.get("meme")
        if meme and not meme_exists(meme):
            meme = None
        if meme and idx == 0:
            meme = None
        if meme and idx - last_idx < rule["min_gap"]:
            meme = None
        if meme and usage.get(meme, 0) >= MAX_USES_PER_MEME:
            meme = None
        if meme and rule["per_card"] and per_card.get(card["card_id"], 0) >= rule["per_card"]:
            meme = None
        if meme:
            usage[meme] = usage.get(meme, 0) + 1
            per_card[card["card_id"]] = per_card.get(card["card_id"], 0) + 1
            last_idx = idx
        else:
            s["meme"] = None
            s["meme_reason"] = None

    # Giới hạn tổng: bỏ dần meme ở vùng dày nhất
    cap = max(1, math.floor(len(flat) * rule["ratio"])) if len(flat) > 1 else 0
    with_meme = [i for i, (_, s) in enumerate(flat) if s.get("meme")]
    while len(with_meme) > cap:
        gaps = []
        for k, i in enumerate(with_meme):
            prev_gap = i - with_meme[k - 1] if k > 0 else 10**6
            next_gap = with_meme[k + 1] - i if k + 1 < len(with_meme) else 10**6
            gaps.append((min(prev_gap, next_gap), -i))
        _, neg_i = min(gaps)
        flat[-neg_i][1]["meme"] = None
        flat[-neg_i][1]["meme_reason"] = None
        with_meme.remove(-neg_i)
    return plan


# ---------------------------------------------------------------------------
# Chuẩn hóa plan
# ---------------------------------------------------------------------------

def finalize_plan(plan: dict, project_cards: list[dict], cfg: dict) -> dict:
    """Ghép thông tin thẻ (ảnh, loại), đánh lại id câu, chuẩn hóa speak_text, áp luật meme."""
    by_id = {c["card_id"]: c for c in project_cards}
    llm_cards = {str(c.get("card_id")): c for c in (plan.get("cards") or []) if isinstance(c, dict)}

    cards_out = []
    for pc in project_cards:
        src = llm_cards.get(pc["card_id"])
        sentences = src.get("sentences", []) if isinstance(src, dict) else []
        if not isinstance(sentences, list):
            sentences = []
        # model nhỏ đôi khi trả câu dạng chuỗi thay vì object
        sentences = [{"display_text": x} if isinstance(x, str) else x for x in sentences]
        sentences = [x for x in sentences if isinstance(x, dict)]
        if not sentences:  # AI bỏ sót → tách câu bằng quy tắc
            sentences = [{"display_text": t} for t in split_sentences(pc.get("body", ""))]
        out_sents = []
        for s in sentences:
            display = str(s.get("display_text", "")).strip()
            speak = normalize_speak_text(str(s.get("speak_text") or display))
            if not display or not has_speakable(speak):
                continue
            out_sents.append({
                "id": "",
                "display_text": display,
                "speak_text": speak,
                "emotion": str(s.get("emotion") or "trung tính")[:40],
                "meme": meme_name(s.get("meme")),
                "meme_reason": str(s.get("meme_reason"))[:200] if s.get("meme_reason") else None,
            })
        for i, s in enumerate(out_sents, start=1):
            s["id"] = f"{pc['card_id']}s{i}"
        if out_sents:
            cards_out.append({
                "card_id": pc["card_id"],
                "image": by_id[pc["card_id"]]["image"],
                "kind": by_id[pc["card_id"]].get("kind", "post"),
                "sentences": out_sents,
            })

    has_post = any(c["kind"] == "post" for c in cards_out)
    has_comment = any(c["kind"] == "comment" for c in cards_out)
    transition = None
    if cfg.get("show_transition", True) and has_post and has_comment:
        transition = (cfg.get("transition_text") or "Và đây là bình luận của cư dân mạng:").strip()

    tags = plan.get("hashtags") or []
    hashtags = []
    for t in tags if isinstance(tags, list) else []:
        t = re.sub(r"\s+", "", str(t))
        if t:
            hashtags.append(t if t.startswith("#") else f"#{t}")

    result = {
        "cards": cards_out,
        "transition_before_comments": transition,
        "title_suggestion": str(plan.get("title_suggestion") or "")[:80],
        "hashtags": hashtags[:6],
    }
    return enforce_meme_rules(result, cfg.get("meme_density", "vừa"))


def validate_user_plan(plan: dict, project_cards: list[dict], cfg: dict) -> dict:
    """Plan do người dùng sửa ở màn hình duyệt: giữ nguyên id/meme đã chọn nhưng vẫn kiểm tra hợp lệ."""
    by_id = {c["card_id"]: c for c in project_cards}
    cards_out = []
    for c in plan.get("cards", []):
        cid = str(c.get("card_id"))
        if cid not in by_id:
            continue
        sents = []
        for s in c.get("sentences", []):
            display = str(s.get("display_text", "")).strip()
            speak = str(s.get("speak_text") or "").strip() or normalize_speak_text(display)
            if not display or not has_speakable(speak):
                continue
            meme = meme_name(s.get("meme"))
            sents.append({
                "id": str(s.get("id") or ""),
                "display_text": display,
                "speak_text": speak,
                "emotion": str(s.get("emotion") or "trung tính"),
                "meme": meme if meme_exists(meme) else None,
                "meme_reason": s.get("meme_reason") if meme_exists(meme) else None,
            })
        ids = [s["id"] for s in sents]
        if len(set(ids)) != len(ids) or not all(ids):
            for i, s in enumerate(sents, start=1):
                s["id"] = f"{cid}s{i}"
        if sents:
            cards_out.append({"card_id": cid, "image": by_id[cid]["image"],
                              "kind": by_id[cid].get("kind", "post"), "sentences": sents})
    plan = {**plan, "cards": cards_out}
    # Người dùng chọn meme thủ công: chỉ chặn meme không tồn tại, không ép mật độ.
    return plan


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def _memes_for_prompt(memes: list[dict]) -> list[dict]:
    return [
        {"file": m["file"], "name": m.get("name", ""), "tags": m.get("tags", []),
         "description": m.get("description", ""), "type": m.get("type", "image")}
        for m in memes if meme_exists(m.get("file"))
    ]


async def create_plan(project_cards: list[dict], memes: list[dict], cfg: dict,
                      llm: LLMBase | None) -> tuple[dict, str | None]:
    """Tạo plan. Trả về (plan, cảnh_báo). llm=None → dùng planner dự phòng."""
    cards_in = [{"card_id": c["card_id"], "kind": c.get("kind", "post"), "body": c.get("body", "")}
                for c in project_cards if (c.get("body") or "").strip()]
    if not cards_in:
        raise ValueError("Chưa có thẻ nào có chữ. Hãy đọc chữ (OCR) hoặc nhập chữ cho thẻ trước.")
    usable = [c for c in project_cards if (c.get("body") or "").strip()]

    if llm is None:
        return fallback_plan(usable, memes, cfg), (
            "Chưa có AI nên dùng chế độ chia câu cơ bản và chọn meme theo từ khóa cảm xúc. "
            "Nhập API key hoặc bật \"Máy này (Ollama)\" trong Cài đặt để AI chọn meme hay hơn."
        )

    prompt = (
        load_prompt("planner.md")
        .replace("{{CARDS_JSON}}", json.dumps(cards_in, ensure_ascii=False, indent=1))
        .replace("{{MEMES_JSON}}", json.dumps(_memes_for_prompt(memes), ensure_ascii=False, indent=1))
        .replace("{{MEME_DENSITY}}", cfg.get("meme_density", "vừa"))
    )
    raw = await llm.complete_json(prompt, validator=_validator([c["card_id"] for c in cards_in]))
    return finalize_plan(raw, usable, cfg), None


# Từ điển cảm xúc cho chế độ không AI: (từ khóa trong câu) → (nhãn meme nên khớp)
EMOTION_LEXICON: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("cười", ("haha", "hihi", "hehe", "kkk", "buồn cười", "hài", "lol", "vui", "cười"),
     ("cười", "hài hước", "buồn cười", "haha", "vui")),
    ("sốc", ("hả", "trời ơi", "trời đất", "sao lại", "không thể tin", "bất ngờ", "sốc", "choáng", "ủa", "thật hả", "!?"),
     ("sốc", "bất ngờ", "không tin nổi", "hả", "ngỡ ngàng", "thắc mắc", "ủa")),
    ("buồn", ("buồn", "khóc", "tội", "thương", "tủi", "đau lòng", "cô đơn", "mất", "nước mắt", "kiệt sức", "mệt"),
     ("buồn", "khóc", "tủi thân", "tội nghiệp", "thương", "đau lòng", "đồng cảm")),
    ("tức", ("tức", "bực", "ghét", "cay", "điên", "vô lý", "bất công", "cộc cằn", "chửi", "gắt", "bất hiếu"),
     ("tức giận", "bức xúc", "cay", "bực mình", "phẫn nộ", "ức chế")),
    ("khinh", ("chụp hình", "sống ảo", "khoe", "giả tạo", "màu mè", "đăng facebook", "caption", "người hùng", "ngoan", "tấm tắc"),
     ("khinh bỉ", "mỉa mai", "ờ hớ", "coi thường", "nhếch mép")),
    ("cạn lời", ("cạn lời", "bó tay", "chịu", "hết nói", "thôi", "chán", "nản", "vô vọng"),
     ("cạn lời", "bó tay", "ngán ngẩm", "chán nản", "trời ơi", "chán")),
    ("đỉnh", ("tinh tế", "tuyệt", "đỉnh", "hay quá", "giỏi", "xịn", "sâu sắc", "trầm trồ", "ngưỡng mộ"),
     ("đỉnh", "ngưỡng mộ", "tuyệt vời", "thán phục", "tinh tế", "xuất sắc")),
    ("nghi ngờ", ("thật không", "chắc gì", "xạo", "nghi", "liệu", "có thật"),
     ("nghi ngờ", "không tin", "hoài nghi", "thật không")),
    ("đồng ý", ("chuẩn", "đúng", "công nhận", "chính xác", "quá đúng", "chân lý", "quy luật"),
     ("đồng ý", "chuẩn", "đúng vậy", "công nhận", "quá đúng")),
    ("hóng", ("drama", "hóng", "tiếp theo", "kể tiếp", "rồi sao"),
     ("hóng", "hóng drama", "tò mò", "chờ xem")),
]


def _emotion_of(text: str) -> tuple[str, tuple[str, ...]] | None:
    low = text.lower()
    best, score = None, 0
    for emo, words, tags in EMOTION_LEXICON:
        # khớp NGUYÊN TỪ (tránh "hả" khớp nhầm trong "phản")
        n = sum(1 for w in words if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low))
        if n > score:
            best, score = (emo, tags), n
    return best


def _meme_for(tags: tuple[str, ...], memes: list[dict], used: dict) -> str | None:
    best, best_score = None, 0
    for m in memes:
        mt = " ".join(str(t).lower() for t in (m.get("tags") or [])) + " " + str(m.get("name", "")).lower() \
            + " " + str(m.get("description", "")).lower()
        sc = sum(1 for t in tags if t in mt) - 0.5 * used.get(m["file"], 0)
        if sc > best_score:
            best, best_score = m["file"], sc
    return best


def fallback_plan(project_cards: list[dict], memes: list[dict], cfg: dict) -> dict:
    """Planner không cần AI: tách câu theo dấu câu, chọn meme theo TỪ KHÓA CẢM XÚC trong câu
    (khớp với nhãn meme); không khớp gì thì câu kết thúc bằng !/? lấy meme xoay vòng."""
    usable = [m for m in memes if meme_exists(m.get("file"))]
    files = [m["file"] for m in usable]
    raw_cards = []
    k = 0
    idx = 0
    used: dict[str, int] = {}
    for c in project_cards:
        sents = []
        for text in split_sentences(c.get("body", "")):
            meme, reason, emotion = None, None, "trung tính"
            emo = _emotion_of(text)
            if emo:
                emotion = emo[0]
            if usable and idx > 0:
                if emo:
                    meme = _meme_for(emo[1], usable, used)
                    if meme:
                        reason = f"Từ khóa cảm xúc: {emo[0]} (chế độ không AI)"
                if not meme and text.rstrip().endswith(("!", "?")) and files:
                    meme = files[k % len(files)]
                    k += 1
                    reason = "Chọn tự động (chế độ không AI)"
            if meme:
                used[meme] = used.get(meme, 0) + 1
            sents.append({"display_text": text, "speak_text": text, "emotion": emotion,
                          "meme": meme, "meme_reason": reason})
            idx += 1
        raw_cards.append({"card_id": c["card_id"], "sentences": sents})
    return finalize_plan({"cards": raw_cards, "title_suggestion": "", "hashtags": ["#threads"]},
                         project_cards, cfg)
