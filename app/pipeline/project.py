"""
project.py — Điều phối toàn bộ quy trình cho một dự án video.

projects/<id>/
  project.json   trạng thái: ảnh gốc, danh sách thẻ (thứ tự, chữ, loại), kết quả
  input/         ảnh người dùng upload
  cards/         ảnh từng thẻ (c1.png...), bản gốc chưa che tên (*_orig.png)
  plan.json      kế hoạch (schema trong spec)
  timeline.json  mốc thời gian đã tính
  render/        file tạm khi render
  output_*.mp4   video kết quả
"""
from __future__ import annotations

import asyncio
import io
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from app.config import PROJECTS_DIR, has_llm, media_dir
from app.llm.base import LLMBase
from app.llm.factory import get_llm
from app.pipeline import card_render, comment_filter, crop, media, memes, ocr, planner
from app.pipeline import timeline as TL
from app.pipeline.caption import suggest_caption
from app.pipeline.render import render_timeline
from app.pipeline.tts import synthesize_many
from app.utils import imread, read_json, safe_filename, unique_path, write_json

ProgressCb = Callable[[float, str], None]


class ProjectError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Lưu trữ
# ---------------------------------------------------------------------------

def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8,32}", pid or ""):
        raise ProjectError("Mã dự án không hợp lệ.")
    d = PROJECTS_DIR / pid
    if not d.exists():
        raise ProjectError("Không tìm thấy dự án (có thể đã bị xóa). Hãy tạo video mới.")
    return d


def create_project() -> dict:
    pid = uuid.uuid4().hex[:12]
    d = PROJECTS_DIR / pid
    for sub in ("input", "cards"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    data = {"id": pid, "created": int(time.time()), "source": None, "url": None,
            "images": [], "cards": [], "next_card": 1, "outputs": [], "caption": None, "warnings": []}
    write_json(d / "project.json", data)
    return data


def load(pid: str) -> dict:
    data = read_json(project_dir(pid) / "project.json")
    if not data:
        raise ProjectError("File project.json bị hỏng.")
    return data


def save(data: dict) -> None:
    write_json(project_dir(data["id"]) / "project.json", data)


def load_plan(pid: str) -> Optional[dict]:
    return read_json(project_dir(pid) / "plan.json")


def save_plan(pid: str, plan: dict) -> None:
    write_json(project_dir(pid) / "plan.json", plan)


def _new_card_id(data: dict) -> str:
    cid = f"c{data.get('next_card', 1)}"
    data["next_card"] = data.get("next_card", 1) + 1
    return cid


def _llm_or_none(cfg: dict) -> Optional[LLMBase]:
    return get_llm(cfg) if has_llm(cfg) else None


# ---------------------------------------------------------------------------
# Nguồn 1: ảnh upload
# ---------------------------------------------------------------------------

def add_images(pid: str, files: list[tuple[str, bytes]]) -> dict:
    """Lưu ảnh, tự cắt thành các thẻ (một ảnh có thể ra nhiều thẻ)."""
    data = load(pid)
    d = project_dir(pid)
    data["source"] = "upload"
    for name, content in files:
        if not content:
            continue
        dest = unique_path(d / "input", safe_filename(name, "anh"))
        if dest.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            dest = dest.with_suffix(".png")
        dest.write_bytes(content)
        rel = f"input/{dest.name}"
        data["images"].append({"file": rel, "name": name})
        try:
            pieces = crop.crop_cards(str(dest), str(d / "cards"), prefix=f"tmp_{dest.stem}")
        except ValueError as exc:
            dest.unlink(missing_ok=True)
            data["images"].pop()
            raise ProjectError(str(exc))
        for piece in pieces:
            cid = _new_card_id(data)
            final = d / "cards" / f"{cid}.png"
            Path(piece["path"]).replace(final)
            shutil.copy2(final, d / "cards" / f"{cid}_orig.png")
            data["cards"].append({
                "card_id": cid, "image": f"cards/{cid}.png", "source_image": rel,
                "source_box": piece["box"], "kind": "post", "body": "", "ocr_done": False,
                "part_index": None, "part_total": None, "author_box": None, "masked": False,
                "uncertain_words": [],
            })
    save(data)
    return data


def recrop_card(pid: str, card_id: str, box: list[float]) -> dict:
    """Cắt tay lại một thẻ từ ảnh gốc của nó."""
    data = load(pid)
    d = project_dir(pid)
    card = _get_card(data, card_id)
    if not card.get("source_image"):
        raise ProjectError("Thẻ này được vẽ tự động, không cắt lại được.")
    out = d / "cards" / f"{card_id}.png"
    crop.manual_crop(str(d / card["source_image"]), box, str(out))
    shutil.copy2(out, d / "cards" / f"{card_id}_orig.png")
    card.update({"source_box": [int(v) for v in box], "ocr_done": False, "masked": False, "author_box": None})
    save(data)
    return data


def add_manual_card(pid: str, source_image: str, box: list[float]) -> dict:
    """Thêm thẻ mới bằng cách kéo khung trên một ảnh gốc."""
    data = load(pid)
    d = project_dir(pid)
    if source_image not in {i["file"] for i in data["images"]}:
        raise ProjectError("Ảnh gốc không thuộc dự án này.")
    cid = _new_card_id(data)
    out = d / "cards" / f"{cid}.png"
    crop.manual_crop(str(d / source_image), box, str(out))
    shutil.copy2(out, d / "cards" / f"{cid}_orig.png")
    data["cards"].append({
        "card_id": cid, "image": f"cards/{cid}.png", "source_image": source_image,
        "source_box": [int(v) for v in box], "kind": "post", "body": "", "ocr_done": False,
        "part_index": None, "part_total": None, "author_box": None, "masked": False, "uncertain_words": [],
    })
    save(data)
    return data


def _get_card(data: dict, card_id: str) -> dict:
    for c in data["cards"]:
        if c["card_id"] == card_id:
            return c
    raise ProjectError(f"Không tìm thấy thẻ {card_id}.")


def update_cards(pid: str, order: Optional[list[str]] = None, edits: Optional[dict] = None,
                 delete: Optional[list[str]] = None) -> dict:
    """Đổi thứ tự / sửa chữ & loại thẻ / xóa thẻ."""
    data = load(pid)
    if delete:
        data["cards"] = [c for c in data["cards"] if c["card_id"] not in set(delete)]
    if edits:
        for cid, fields in edits.items():
            card = _get_card(data, cid)
            if "body" in fields:
                card["body"] = str(fields["body"] or "").strip()
            if fields.get("kind") in ("post", "comment"):
                card["kind"] = fields["kind"]
    if order:
        pos = {cid: i for i, cid in enumerate(order)}
        data["cards"].sort(key=lambda c: pos.get(c["card_id"], 10**6))
    save(data)
    return data


async def run_ocr(pid: str, cfg: dict, only_missing: bool = True) -> dict:
    """AI đọc chữ cho các thẻ ảnh, che tên người bình luận (và tác giả nếu bật), sắp xếp theo số thứ tự."""
    data = load(pid)
    d = project_dir(pid)
    targets = [c for c in data["cards"] if c.get("source_image") and (not only_missing or not c.get("ocr_done"))]
    if not targets:
        return data
    if not has_llm(cfg):
        raise ProjectError("Cần API key AI để đọc chữ từ ảnh. Vào Cài đặt để nhập key, "
                           "hoặc tự gõ chữ vào ô dưới mỗi thẻ.")
    llm = get_llm(cfg)
    for c in targets:  # luôn OCR trên ảnh gốc chưa che
        orig = d / "cards" / f"{c['card_id']}_orig.png"
        if orig.exists():
            shutil.copy2(orig, d / c["image"])
    results = await ocr.ocr_cards(llm, [str(d / c["image"]) for c in targets])

    errors = []
    failed = 0
    for c, res in zip(targets, results):
        if isinstance(res, Exception):
            errors.append(f"{c['card_id']}: {res}")
            failed += 1
            continue
        # Thẻ có số thứ tự "x/y" là phần nối tiếp của bài gốc (AI hay nhầm là bình luận vì có đường kẻ dọc)
        is_post_part = bool(res["part_total"] and res["part_total"] > 1)
        c.update({"body": res["body"], "part_index": res["part_index"], "part_total": res["part_total"],
                  "author_box": res["author_box"],
                  "kind": "post" if is_post_part or not res["is_reply"] else "comment",
                  "uncertain_words": res["uncertain_words"], "ocr_done": True, "masked": False})
        if c["kind"] == "comment" or cfg.get("hide_author"):
            path = d / c["image"]
            img = imread(path)
            regions = crop.detect_author_regions(img) if img is not None else []
            if not regions and img is not None:
                regions = crop.clamp_llm_box(res["author_box"], img.shape[1], img.shape[0])
            if regions:
                crop.mask_regions(str(path), regions)
                c["masked"] = True
            else:
                errors.append(f"{c['card_id']}: không tìm thấy vùng tên để che — hãy kiểm tra thẻ này "
                              "(cắt lại cho thấy rõ avatar và tên).")

    # Sắp xếp: nếu mọi thẻ bài gốc đều có số thứ tự (vd 1/7) thì xếp theo số đó; bình luận giữ nguyên sau bài.
    posts = [c for c in data["cards"] if c["kind"] == "post"]
    if posts and all(c.get("part_index") for c in posts):
        posts.sort(key=lambda c: c["part_index"])
        comments = [c for c in data["cards"] if c["kind"] != "post"]
        data["cards"] = posts + comments
    data["warnings"] = errors
    save(data)
    if failed == len(targets):
        raise ProjectError("Không đọc được chữ ở thẻ nào. " + errors[0])
    return data


# ---------------------------------------------------------------------------
# Nguồn 2: link Threads
# ---------------------------------------------------------------------------

def _save_media(d: Path, cid: str, items: list[dict], warnings: list[str]) -> list[str]:
    """Tải ảnh đính kèm của bài/bình luận về cards/<cid>_m<k>.jpg, trả về đường dẫn tương đối."""
    from app.pipeline.threads_fetch import download_media
    saved = []
    for k, m in enumerate(items or []):
        rel = f"cards/{cid}_m{k}.jpg"
        try:
            raw = download_media(m["url"])
            with Image.open(io.BytesIO(raw)) as im:
                im.convert("RGB").save(d / rel, "JPEG", quality=92)
            saved.append(rel)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Không tải được ảnh {k + 1} của thẻ {cid} ({exc}); thẻ chỉ có chữ.")
    return saved


async def import_threads(pid: str, url: str, cookie: str, cfg: dict) -> dict:
    from app.pipeline.threads_fetch import fetch_thread

    data = load(pid)
    d = project_dir(pid)
    fetched = await fetch_thread(url, cookie)
    post = fetched["post"]
    llm = _llm_or_none(cfg)

    candidates = comment_filter.filter_basic(fetched["comments"])
    post_text = "\n\n".join(p["text"] for p in post["parts"])
    warnings = []
    try:
        chosen = await comment_filter.select_comments(candidates, post_text, cfg, llm)
    except Exception as exc:
        warnings.append(f"AI lọc bình luận lỗi ({exc}); đã lấy theo lượt thích.")
        chosen = candidates[: int(cfg.get("comment_max", 6))]
    chosen = comment_filter.anonymize(chosen)

    # Xóa thẻ cũ (nếu lấy lại link)
    for c in data["cards"]:
        for suffix in ("", "_orig"):
            (d / "cards" / f"{c['card_id']}{suffix}.png").unlink(missing_ok=True)
        for m in c.get("media") or []:
            (d / m).unlink(missing_ok=True)
    data.update({"source": "threads", "url": url, "cards": [], "images": [],
                 "fetched": {"comments_total": len(fetched["comments"]), "candidates": len(candidates)}})

    hide = bool(cfg.get("hide_author"))
    author_name = "Tác giả" if hide or not post["author"] else post["author"]
    n_parts = len(post["parts"])
    when = card_render.display_time(post.get("time"))
    (d / "cards").mkdir(parents=True, exist_ok=True)
    for i, part in enumerate(post["parts"], start=1):
        cid = _new_card_id(data)
        card_media = await asyncio.to_thread(_save_media, d, cid, part.get("media"), warnings)
        if not part["text"].strip():
            warnings.append(f"Phần {i} của bài chỉ có ảnh, không có chữ: hãy gõ chữ cho thẻ này "
                            "(thẻ không có chữ sẽ không được đưa vào video).")
        card_render.render_card_image({
            "body": part["text"], "kind": "post", "display_name": author_name, "gray_avatar": hide,
            "media": [str(d / m) for m in card_media],
            "time": when, "part_index": i if n_parts > 1 else None, "part_total": n_parts if n_parts > 1 else None,
            "likes": post.get("likes") if i == 1 else None, "replies": post.get("replies") if i == 1 else None,
        }, d / "cards" / f"{cid}.png")
        data["cards"].append({"card_id": cid, "image": f"cards/{cid}.png", "source_image": None,
                              "kind": "post", "body": part["text"], "ocr_done": True, "media": card_media,
                              "part_index": i, "part_total": n_parts, "display_name": author_name})
    for c in chosen:
        cid = _new_card_id(data)
        card_media = await asyncio.to_thread(_save_media, d, cid, c.get("media"), warnings)
        card_render.render_card_image({
            "body": c["text"], "kind": "comment", "display_name": c["display_name"], "gray_avatar": True,
            "media": [str(d / m) for m in card_media],
            "time": card_render.display_time(c.get("time")), "likes": c.get("likes"),
        }, d / "cards" / f"{cid}.png")
        data["cards"].append({"card_id": cid, "image": f"cards/{cid}.png", "source_image": None,
                              "kind": "comment", "body": c["text"], "ocr_done": True, "media": card_media,
                              "display_name": c["display_name"], "stance": c.get("stance")})
    data["warnings"] = warnings
    save(data)
    return data


def rerender_drawn_card(pid: str, card_id: str) -> None:
    """Vẽ lại thẻ tự vẽ sau khi người dùng sửa chữ."""
    data = load(pid)
    card = _get_card(data, card_id)
    if card.get("source_image"):
        return
    d = project_dir(pid)
    card_render.render_card_image({
        "body": card["body"], "kind": card["kind"], "display_name": card.get("display_name"),
        "gray_avatar": card["kind"] == "comment" or card.get("display_name") == "Tác giả",
        "media": [str(d / m) for m in card.get("media") or []],
        "part_index": card.get("part_index") if (card.get("part_total") or 0) > 1 else None,
        "part_total": card.get("part_total") if (card.get("part_total") or 0) > 1 else None,
    }, d / card["image"])


# ---------------------------------------------------------------------------
# Lên kế hoạch
# ---------------------------------------------------------------------------

async def make_plan(pid: str, cfg: dict) -> tuple[dict, Optional[str]]:
    data = load(pid)
    cards = [c for c in data["cards"] if (c.get("body") or "").strip()]
    if not cards:
        raise ProjectError("Chưa có thẻ nào có chữ. Hãy bấm \"Đọc chữ\" hoặc tự nhập chữ cho thẻ.")
    llm = _llm_or_none(cfg)
    try:
        plan, warning = await planner.create_plan(cards, memes.list_memes(), cfg, llm)
    except Exception as exc:
        if llm is None:
            raise
        plan = planner.fallback_plan(cards, memes.list_memes(), cfg)
        warning = f"AI lên kế hoạch bị lỗi ({exc}). Đã dùng chế độ chia câu cơ bản — bạn có thể sửa ở bảng duyệt."
    save_plan(pid, plan)
    return plan, warning


def update_plan(pid: str, plan: dict, cfg: dict) -> dict:
    data = load(pid)
    fixed = planner.validate_user_plan(plan, data["cards"], cfg)
    save_plan(pid, fixed)
    return fixed


# ---------------------------------------------------------------------------
# Render (chạy trong job nền)
# ---------------------------------------------------------------------------

def _card_sizes(d: Path, plan: dict) -> dict[str, tuple[int, int]]:
    sizes = {}
    for c in TL.sequence_cards(plan):
        p = d / c["image"]
        if not p.exists():
            raise ProjectError(f"Thiếu ảnh thẻ {c['image']}.")
        with Image.open(p) as im:
            sizes[c["card_id"]] = im.size
    return sizes


def set_background(pid: str, file: Optional[str]) -> dict:
    """Chọn video nền cho dự án (None = ngẫu nhiên)."""
    data = load(pid)
    if file:
        p = media.safe_media_path("background", file)
        if not p.exists():
            raise ProjectError(f"Không tìm thấy video nền '{file}' trong thư mục nền.")
    data["background"] = file or None
    save(data)
    return data


def set_music(pid: str, file: Optional[str]) -> dict:
    """Chọn nhạc nền cho dự án: None/"" = ngẫu nhiên, "__none__" = không nhạc, tên file = bài cụ thể."""
    from app.pipeline.render import NO_MUSIC, music_files
    data = load(pid)
    if file and file != NO_MUSIC and file not in {p.name for p in music_files()}:
        raise ProjectError(f"Không tìm thấy bài nhạc '{file}' trong thư mục nhạc nền.")
    data["music"] = file or None
    save(data)
    return data


def approve(pid: str) -> dict:
    """Duyệt: chép video đã render sang thư mục 'video đã duyệt' + file .txt tiêu đề/caption/hashtag."""
    data = load(pid)
    d = project_dir(pid)
    outs = [o for o in data.get("outputs", []) if (d / o["file"]).exists()]
    if not outs:
        raise ProjectError("Chưa có video nào để duyệt. Hãy render trước.")
    dest_dir = media_dir("approved")
    cap = data.get("caption") or {}
    title = cap.get("title") or ""
    from app.pipeline.caption import clean_topic, fallback_topic
    topic = clean_topic(cap.get("topic") or "") or fallback_topic(load_plan(pid) or {}) or clean_topic(title)
    stamp = time.strftime("%d-%m-%Y %Hh%M")
    saved = []
    for o in outs:
        dest = dest_dir / media.approved_name(topic, stamp, o.get("part"))
        if dest.exists():
            dest = unique_path(dest_dir, dest.name)
        shutil.copy2(d / o["file"], dest)
        lines = [f"Chủ đề: {topic}", f"Tiêu đề: {cap.get('title') or title}", "", cap.get("caption") or "", "",
                 " ".join(cap.get("hashtags") or [])]
        if o.get("part"):
            lines.insert(0, f"Part {o['part']}")
        dest.with_suffix(".txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        saved.append(dest.name)
    data["approved"] = saved
    save(data)
    return {"files": saved, "folder": str(dest_dir), "topic": topic}


async def ensure_topic(pid: str, cfg: dict) -> None:
    """Dự án render bằng bản cũ (chưa có 'topic') → nhờ AI tóm tắt chủ đề trước khi lưu. Lỗi thì bỏ qua."""
    data = load(pid)
    cap = data.get("caption") or {}
    if cap.get("topic"):
        return
    plan = load_plan(pid) or {}
    try:
        new = await suggest_caption(plan, _llm_or_none(cfg))
    except Exception:
        return
    cap = {**new, **{k: v for k, v in cap.items() if v}}
    cap["topic"] = new.get("topic", "")
    data = load(pid)
    data["caption"] = cap
    save(data)


async def render_project(pid: str, cfg: dict, progress: ProgressCb) -> dict:
    d = project_dir(pid)
    data = load(pid)
    cfg = {**cfg, "background_file": data.get("background")}
    music_choice = data.get("music")
    if not music_choice and cfg.get("music_mode") == "none":
        music_choice = "__none__"
    if not music_choice or music_choice != "__none__":
        # chọn 1 lần cho cả dự án → các Part dùng chung một bài
        from app.pipeline.render import pick_music
        m = pick_music(music_choice or None)
        music_choice = m.name if m else "__none__"
    cfg["music_file"] = music_choice
    plan = load_plan(pid)
    if not plan or not plan.get("cards"):
        raise ProjectError("Chưa có kế hoạch. Hãy bấm \"Lên kế hoạch\" trước.")
    plan = planner.validate_user_plan(plan, data["cards"], cfg)

    trans = (plan.get("transition_before_comments") or "").strip()
    if trans:
        card_render.render_transition_card(trans, d / "cards" / "transition.png")

    # 1) Giọng đọc (0–30%)
    texts = {s["id"]: s["speak_text"] for c in plan["cards"] for s in c["sentences"]}
    if trans:
        texts[TL.TRANSITION_ID] = planner.normalize_speak_text(trans)
    progress(0.01, f"Đang tạo giọng đọc cho {len(texts)} câu…")
    audio = await synthesize_many(
        texts, cfg, lambda done, total: progress(0.30 * done / total, f"Giọng đọc: {done}/{total} câu"),
        on_note=lambda msg: progress(0.0, msg))

    # 2) Timeline
    tl = TL.build_timeline(plan, audio, _card_sizes(d, plan), float(cfg.get("max_duration", 90)))
    write_json(d / "timeline.json", tl)
    n = len(tl["parts"])
    progress(0.31, f"Timeline: {tl['total_duration']:.1f} giây" + (f", chia {n} phần" if n > 1 else ""))

    # 3) Render (31–97%)
    outputs = await asyncio.to_thread(
        render_timeline, tl, d, cfg, lambda f, msg: progress(0.31 + 0.66 * f, msg))

    # 4) Gợi ý caption (B5)
    progress(0.98, "Đang gợi ý tiêu đề, caption, hashtag…")
    try:
        cap = await suggest_caption(plan, _llm_or_none(cfg))
    except Exception:
        cap = await suggest_caption(plan, None)

    data = load(pid)
    data["outputs"] = [{"file": p.name, "part": part.get("index"), "duration": part["duration"]}
                       for p, part in zip(outputs, tl["parts"])]
    data["caption"] = cap
    data["approved"] = []
    save(data)
    info = read_json(d / "render" / ("part1" if len(tl["parts"]) > 1 else "main") / "render_info.json", {}) or {}
    return {"outputs": data["outputs"], "caption": cap, "duration": tl["total_duration"],
            "background": info.get("background"), "music": info.get("music")}
