"""
main.py — FastAPI: giao diện web + API cho tool dựng video Threads.

Chạy: uvicorn app.main:app --port 8000   (hoặc run.bat / run.sh)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import assets
from app.config import (BASE_DIR, CACHE_DIR, DEFAULT_CONFIG, LIBRARY_DIR, PROJECTS_DIR, SECRET_KEYS,
                        get_config, has_llm, public_config, save_config, load_config)
from app.llm.base import LLMError
from app.config import MEDIA_KINDS, media_dir
from app.pipeline import media
from app.pipeline import memes as meme_lib
from app.pipeline import project as P
from app.pipeline.tts import list_voices, synthesize_cached
from app.pipeline.tts.base import TTSError

log = logging.getLogger("app")
STATIC_DIR = BASE_DIR / "app" / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assets.ensure_dirs()
    assets.ensure_pop_sfx()
    await asyncio.to_thread(assets.ensure_fonts)
    yield


app = FastAPI(title="Threads Video Tool", version="1.0.0", lifespan=lifespan)
assets.ensure_dirs()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/library", StaticFiles(directory=str(LIBRARY_DIR)), name="library")
app.mount("/projects", StaticFiles(directory=str(PROJECTS_DIR)), name="projects")


# ---------------------------------------------------------------------------
# Lỗi → JSON tiếng Việt
# ---------------------------------------------------------------------------

USER_ERRORS = (P.ProjectError, LLMError, TTSError, ValueError, KeyError, FileNotFoundError)


@app.exception_handler(Exception)
async def _unhandled(_req: Request, exc: Exception):
    log.error("Lỗi không mong đợi: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": f"Lỗi không mong đợi: {exc}"})


def _user_error(exc: Exception) -> HTTPException:
    msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
    return HTTPException(status_code=400, detail=msg)


async def _guard(coro):
    try:
        return await coro
    except HTTPException:
        raise
    except USER_ERRORS as exc:
        raise _user_error(exc)
    except Exception as exc:
        if exc.__class__.__name__ == "ThreadsFetchError":
            raise HTTPException(status_code=502, detail=str(exc))
        raise


def _sync_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except USER_ERRORS as exc:
        raise _user_error(exc)


# ---------------------------------------------------------------------------
# Trang
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def page_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/memes", include_in_schema=False)
async def page_memes():
    return FileResponse(STATIC_DIR / "memes.html")


@app.get("/settings", include_in_schema=False)
async def page_settings():
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/api/status")
async def status():
    """Tình trạng thư viện để giao diện cảnh báo sớm."""
    import shutil
    cfg = get_config()
    bgs = media.list_backgrounds()
    from app.pipeline.render import music_files
    music = [p.name for p in music_files()]
    return {
        "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "llm_ready": has_llm(cfg), "llm_provider": cfg.get("llm_provider"),
        "backgrounds": len(bgs), "music": len(music), "memes": len(meme_lib.list_memes()),
        "auto_mode": bool(cfg.get("auto_mode")),
    }


# ---------------------------------------------------------------------------
# Dự án
# ---------------------------------------------------------------------------

class BackgroundBody(BaseModel):
    file: Optional[str] = None


class MusicBody(BaseModel):
    file: Optional[str] = None


class CardsUpdate(BaseModel):
    order: Optional[List[str]] = None
    edits: Optional[Dict[str, Dict[str, Any]]] = None
    delete: Optional[List[str]] = None


class CropBody(BaseModel):
    box: List[float]
    source_image: Optional[str] = None


class ThreadsBody(BaseModel):
    url: str
    cookie: Optional[str] = None


class PlanBody(BaseModel):
    plan: Dict[str, Any]


class TextBody(BaseModel):
    text: str


def _project_view(data: dict) -> dict:
    d = PROJECTS_DIR / data["id"]
    v = int(time.time())
    for c in data.get("cards", []):
        c["image_url"] = f"/projects/{data['id']}/{c['image']}?v={v}"
        if c.get("source_image"):
            c["source_url"] = f"/projects/{data['id']}/{c['source_image']}"
    for img in data.get("images", []):
        img["url"] = f"/projects/{data['id']}/{img['file']}"
    for o in data.get("outputs", []):
        o["url"] = f"/projects/{data['id']}/{o['file']}"
        o["exists"] = (d / o["file"]).exists()
    return data


@app.post("/api/projects")
async def api_new_project():
    return _project_view(P.create_project())


@app.get("/api/projects/{pid}")
async def api_get_project(pid: str):
    data = _sync_guard(P.load, pid)
    return {"project": _project_view(data), "plan": _sync_guard(P.load_plan, pid)}


@app.post("/api/projects/{pid}/images")
async def api_upload_images(pid: str, files: List[UploadFile] = File(...)):
    payload = [(f.filename or "anh.png", await f.read()) for f in files]
    if not payload:
        raise HTTPException(400, "Chưa chọn ảnh nào.")
    data = await asyncio.to_thread(_sync_guard, P.add_images, pid, payload)
    return _project_view(data)


@app.post("/api/projects/{pid}/cards")
async def api_update_cards(pid: str, body: CardsUpdate):
    data = _sync_guard(P.update_cards, pid, body.order, body.edits, body.delete)
    if body.edits:
        for cid in body.edits:
            if any(c["card_id"] == cid and not c.get("source_image") for c in data["cards"]):
                await asyncio.to_thread(P.rerender_drawn_card, pid, cid)
    return _project_view(P.load(pid))


@app.post("/api/projects/{pid}/cards/{card_id}/crop")
async def api_recrop(pid: str, card_id: str, body: CropBody):
    return _project_view(await asyncio.to_thread(_sync_guard, P.recrop_card, pid, card_id, body.box))


@app.post("/api/projects/{pid}/cards/manual")
async def api_manual_card(pid: str, body: CropBody):
    if not body.source_image:
        raise HTTPException(400, "Thiếu ảnh gốc.")
    return _project_view(await asyncio.to_thread(_sync_guard, P.add_manual_card, pid, body.source_image, body.box))


@app.post("/api/projects/{pid}/ocr")
async def api_ocr(pid: str, force: bool = False):
    data = await _guard(P.run_ocr(pid, get_config(), only_missing=not force))
    return _project_view(data)


@app.post("/api/projects/{pid}/threads")
async def api_threads(pid: str, body: ThreadsBody):
    cfg = get_config()
    cookie = body.cookie if body.cookie is not None and body.cookie.strip() else cfg.get("threads_cookie", "")
    data = await _guard(P.import_threads(pid, body.url, cookie, cfg))
    return _project_view(data)


@app.post("/api/projects/{pid}/plan")
async def api_plan(pid: str):
    plan, warning = await _guard(P.make_plan(pid, get_config()))
    return {"plan": plan, "warning": warning}


@app.put("/api/projects/{pid}/plan")
async def api_save_plan(pid: str, body: PlanBody):
    return {"plan": _sync_guard(P.update_plan, pid, body.plan, get_config())}


@app.post("/api/projects/{pid}/tts-preview")
async def api_tts_preview(pid: str, body: TextBody):
    _sync_guard(P.project_dir, pid)
    return await _guard(_tts_url(body.text, get_config()))


async def _tts_url(text: str, cfg: dict) -> dict:
    wav, dur = await synthesize_cached(text, cfg)
    return {"audio_url": f"/api/audio/{Path(wav).stem}", "duration": round(dur, 2)}


@app.get("/api/audio/{key}")
async def api_audio(key: str):
    if not key.isalnum():
        raise HTTPException(404, "Không tìm thấy âm thanh.")
    p = CACHE_DIR / "tts" / f"{key}.wav"
    if not p.exists():
        raise HTTPException(404, "Không tìm thấy âm thanh.")
    return FileResponse(p, media_type="audio/wav")


@app.get("/api/projects/{pid}/download/{filename}")
async def api_download(pid: str, filename: str):
    d = _sync_guard(P.project_dir, pid)
    p = (d / Path(filename).name)
    if not p.exists() or p.suffix != ".mp4":
        raise HTTPException(404, "Không tìm thấy video.")
    return FileResponse(p, media_type="video/mp4", filename=p.name)


# ---------------------------------------------------------------------------
# Job render (nền) + tiến độ
# ---------------------------------------------------------------------------

JOBS: Dict[str, dict] = {}
_TASKS: set = set()  # giữ tham chiếu để task nền không bị thu gom rác


async def _run_render_job(job_id: str, pid: str) -> None:
    job = JOBS[job_id]
    started = time.time()

    def progress(frac: float, msg: str) -> None:
        job["progress"] = round(max(job["progress"], min(frac, 1.0)), 4)
        job["message"] = msg
        if 0.32 < frac < 1:
            elapsed = time.time() - started
            job["eta"] = round(elapsed / frac * (1 - frac), 1)
        job["log"].append({"t": round(time.time() - started, 1), "msg": msg})
        del job["log"][:-60]

    try:
        result = await P.render_project(pid, get_config(), progress)
        job.update(status="done", progress=1.0, message="Hoàn thành!", result=result,
                   elapsed=round(time.time() - started, 1))
        data = P.load(pid)
        job["result"]["outputs"] = _project_view(data)["outputs"]
    except USER_ERRORS as exc:
        job.update(status="error", message=str(exc.args[0] if isinstance(exc, KeyError) else exc))
    except Exception as exc:
        log.error("Render lỗi: %s\n%s", exc, traceback.format_exc())
        job.update(status="error", message=f"Render thất bại: {exc}")


@app.post("/api/projects/{pid}/background")
async def api_set_background(pid: str, body: BackgroundBody):
    data = _sync_guard(P.set_background, pid, body.file)
    return {"background": data.get("background")}


@app.post("/api/projects/{pid}/music")
async def api_set_music(pid: str, body: MusicBody):
    data = _sync_guard(P.set_music, pid, body.file)
    return {"music": data.get("music")}


@app.post("/api/projects/{pid}/approve")
async def api_approve(pid: str):
    await P.ensure_topic(pid, get_config())
    return await asyncio.to_thread(_sync_guard, P.approve, pid)


@app.post("/api/projects/{pid}/render")
async def api_render(pid: str):
    _sync_guard(P.project_dir, pid)
    for j in JOBS.values():
        if j["project_id"] == pid and j["status"] == "running":
            return {"job_id": j["id"]}
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "project_id": pid, "status": "running", "progress": 0.0,
                    "message": "Đang chuẩn bị…", "eta": None, "log": [], "result": None}
    task = asyncio.create_task(_run_render_job(job_id, pid))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ (server có thể đã khởi động lại).")
    return job


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Không tìm thấy tác vụ.")

    async def gen():
        last = None
        while True:
            job = JOBS.get(job_id)
            if job is None:
                break
            snap = json.dumps({k: job[k] for k in ("status", "progress", "message", "eta", "result")},
                              ensure_ascii=False)
            if snap != last:
                yield f"data: {snap}\n\n"
                last = snap
            else:
                yield ": ping\n\n"
            if job["status"] != "running":
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Ba thư mục: video nền, meme, video đã duyệt
# ---------------------------------------------------------------------------

def _kind(kind: str) -> str:
    if kind not in MEDIA_KINDS:
        raise HTTPException(404, "Không tìm thấy.")
    return kind


@app.get("/api/library")
async def api_library():
    bgs, approved, music = await asyncio.gather(asyncio.to_thread(media.list_backgrounds),
                                                asyncio.to_thread(media.list_approved),
                                                asyncio.to_thread(media.list_music))
    return {"backgrounds": bgs, "approved": approved, "music": music, "memes": meme_lib.list_memes(),
            "dirs": {k: str(media_dir(k)) for k in MEDIA_KINDS}}


@app.get("/api/media/{kind}/{file}")
async def api_media(kind: str, file: str):
    p = _sync_guard(media.safe_media_path, _kind(kind), file)
    if not p.exists():
        raise HTTPException(404, "Không tìm thấy file.")
    if p.suffix.lower() == ".txt":
        return FileResponse(p, media_type="text/plain; charset=utf-8")
    return FileResponse(p)


@app.get("/api/thumb/{kind}/{file}")
async def api_thumb(kind: str, file: str):
    try:
        p = await asyncio.to_thread(media.thumbnail, _kind(kind), file)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/open-folder/{kind}")
async def api_open_folder(kind: str):
    return {"path": media.open_folder(_kind(kind))}


@app.post("/api/backgrounds")
async def api_upload_backgrounds(files: List[UploadFile] = File(...)):
    added, errors = [], []
    exts = media.VIDEO_EXTS | {".jpg", ".jpeg", ".png", ".webp"}
    for f in files:
        try:
            added.append(await asyncio.to_thread(media.add_file, "background", f.filename or "nen.mp4", f.file, exts))
        except ValueError as exc:
            errors.append(str(exc))
    if not added and errors:
        raise HTTPException(400, " ".join(errors))
    return {"added": added, "errors": errors}


@app.post("/api/music")
async def api_upload_music(files: List[UploadFile] = File(...)):
    added, errors = [], []
    for f in files:
        try:
            added.append(await asyncio.to_thread(media.add_file, "music", f.filename or "nhac.mp3", f.file, media.AUDIO_EXTS))
        except ValueError as exc:
            errors.append(str(exc))
    if not added and errors:
        raise HTTPException(400, " ".join(errors))
    return {"added": added, "errors": errors}


@app.delete("/api/files/{kind}/{file}")
async def api_delete_file(kind: str, file: str):
    if _kind(kind) == "meme":
        _sync_guard(meme_lib.delete_meme, file)
    else:
        _sync_guard(media.delete_file, kind, file)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Thư viện meme
# ---------------------------------------------------------------------------

class MemeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[Any] = None


@app.get("/api/memes")
async def api_memes():
    return {"memes": meme_lib.list_memes()}


@app.post("/api/memes")
async def api_upload_memes(files: List[UploadFile] = File(...)):
    added, errors = [], []
    for f in files:
        try:
            added.append(meme_lib.add_meme(f.filename or "meme.png", await f.read()))
        except ValueError as exc:
            errors.append(str(exc))
    if not added and errors:
        raise HTTPException(400, " ".join(errors))
    return {"added": added, "errors": errors}


@app.put("/api/memes/{file}")
async def api_update_meme(file: str, body: MemeUpdate):
    return {"meme": _sync_guard(meme_lib.update_meme, file, body.model_dump())}


@app.delete("/api/memes/{file}")
async def api_delete_meme(file: str):
    _sync_guard(meme_lib.delete_meme, file)
    return {"ok": True}


@app.post("/api/memes/{file}/tag-ai")
async def api_tag_meme(file: str):
    from app.llm.factory import get_llm
    cfg = get_config()
    if not has_llm(cfg):
        raise HTTPException(400, "Cần API key AI để gắn nhãn. Vào Cài đặt để nhập key.")
    return {"meme": await _guard(meme_lib.tag_meme(file, get_llm(cfg)))}


@app.post("/api/memes/{file}/remove-bg")
async def api_remove_bg(file: str):
    return {"meme": await asyncio.to_thread(_sync_guard, meme_lib.remove_white_background, file)}


# ---------------------------------------------------------------------------
# Cài đặt
# ---------------------------------------------------------------------------

class SettingsBody(BaseModel):
    settings: Dict[str, Any]


class TestTTSBody(BaseModel):
    text: Optional[str] = None
    tts_engine: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_speed: Optional[str] = None


NUMERIC = {"music_volume": (0.0, 1.0), "sfx_volume": (0.0, 1.0), "max_duration": (15, 600),
           "comment_min": (1, 10), "comment_max": (1, 15)}
BOOLEAN = {"hide_author", "show_transition", "auto_mode", "watermark", "meme_video_audio"}
FOLDER_KEYS = {"background_dir", "meme_dir", "approved_dir", "music_dir"}
CHOICES = {"llm_provider": {"gemini", "claude", "openai", "zai", "openrouter", "ollama"},
           "fallback_provider": {"", "gemini", "claude", "openai", "zai", "openrouter", "ollama"},
           "tts_engine": {"edge", "vieneu"},
           "meme_density": {"ít", "vừa", "nhiều"}, "music_mode": {"random", "none"}}


@app.get("/api/settings")
async def api_get_settings():
    return {"settings": public_config(), "voices": list_voices()}


@app.post("/api/settings")
async def api_save_settings(body: SettingsBody):
    cfg = load_config()
    for k, v in body.settings.items():
        if k not in DEFAULT_CONFIG:
            continue
        if k in SECRET_KEYS:
            v = (v or "").strip() if isinstance(v, str) else ""
            if v.startswith("****"):
                continue            # giữ key cũ khi frontend gửi lại dạng che
            if v == "" and body.settings.get(f"{k}_clear") is not True:
                continue            # ô trống = không đổi (muốn xóa phải bấm "Xóa")
        elif k in NUMERIC:
            lo, hi = NUMERIC[k]
            try:
                v = max(lo, min(hi, type(DEFAULT_CONFIG[k])(v)))
            except (TypeError, ValueError):
                raise HTTPException(400, f"Giá trị '{k}' không hợp lệ.")
        elif k in BOOLEAN:
            v = bool(v)
        elif k in CHOICES and v not in CHOICES[k]:
            raise HTTPException(400, f"Giá trị '{v}' không hợp lệ cho {k}.")
        elif k in FOLDER_KEYS:
            v = str(v or "").strip().strip('"') or DEFAULT_CONFIG[k]
            try:
                media_dir({v2: k2 for k2, v2 in MEDIA_KINDS.items()}[k], {**cfg, k: v})
            except OSError as exc:
                raise HTTPException(400, f"Không tạo/mở được thư mục '{v}': {exc}")
        elif k == "tts_speed":
            v = str(v).strip()
            if not v.endswith("%"):
                v += "%"
            if not v.startswith(("+", "-")):
                v = "+" + v
        cfg[k] = v
    for k in SECRET_KEYS:
        if body.settings.get(f"{k}_clear") is True:
            cfg[k] = ""
    if cfg["comment_max"] < cfg["comment_min"]:
        cfg["comment_max"] = cfg["comment_min"]
    save_config(cfg)
    return {"settings": public_config()}


class OllamaPullBody(BaseModel):
    model: str


@app.get("/api/ollama/status")
async def api_ollama_status():
    from app.llm.ollama import ollama_status
    cfg = get_config()
    return await ollama_status(cfg.get("ollama_url") or "")


@app.post("/api/ollama/pull")
async def api_ollama_pull(body: OllamaPullBody):
    """Tải model về máy (stream từng dòng JSON tiến độ)."""
    import json as _json
    from app.llm.ollama import pull_model
    cfg = get_config()
    name = (body.model or "").strip()
    if not name or any(ch in name for ch in " \"\n"):
        raise HTTPException(400, "Tên model không hợp lệ.")

    async def gen():
        async for ev in pull_model(cfg.get("ollama_url") or "", name):
            yield _json.dumps(ev, ensure_ascii=False) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/settings/test-llm")
async def api_test_llm():
    from app.llm.factory import get_llm
    cfg = get_config()
    try:
        return {"ok": True, "message": await get_llm(cfg).test_connection()}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@app.post("/api/settings/test-tts")
async def api_test_tts(body: TestTTSBody):
    cfg = get_config()
    for k in ("tts_engine", "tts_voice", "tts_speed"):
        if getattr(body, k):
            cfg[k] = getattr(body, k)
    text = body.text or "Xin chào, đây là giọng đọc thử của tool dựng video Threads."
    return await _guard(_tts_url(text, cfg))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
