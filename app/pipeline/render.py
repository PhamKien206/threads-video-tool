"""
render.py — Dựng video MP4 bằng một lệnh FFmpeg (filter_complex) cho mỗi Part.

- Nền: file người dùng chọn trong thư mục nền (mặc định ./nen_video), hoặc ngẫu nhiên tránh trùng 3 lần render gần nhất;
  scale + crop 1080×1920, eq=brightness=-0.08, lặp lại nếu ngắn hơn video.
- Thẻ: theo vị trí/hiệu ứng đã tính trong timeline.py (fade + trượt).
- Meme: khung hình nảy 0 → 1,1 → 1,0 trong 0,3 s được dựng sẵn bằng Pillow (PNG trong suốt, GIF/WebP động).
- Âm thanh: giọng đọc + "bụp" (ghép chính xác tới từng mẫu âm bằng numpy) + nhạc nền (12%, fade out 1 s cuối),
  chuẩn hóa loudnorm −14 LUFS.
- Tiến độ: phân tích `-progress pipe:1`.
"""
from __future__ import annotations

import json
import math
import random
import re
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageSequence

from app.config import LIBRARY_DIR, media_dir
from app.pipeline import timeline as TL
from app.pipeline.media import has_audio, safe_media_path
from app.utils import ffprobe_duration, read_json, require_binary, run_ffmpeg, write_json

FPS = 30
H264_PRESET = "veryfast"
H264_CRF = 20
SAMPLE_RATE = 44100
MEME_MAX_W = 900
BOUNCE_DUR = 0.3
MEME_FADE_OUT = 0.2

MUSIC_DIR = LIBRARY_DIR / "music"
HISTORY_PATH = LIBRARY_DIR / ".render_history.json"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

ProgressCb = Optional[Callable[[float, str], None]]


# ---------------------------------------------------------------------------
# Thư viện: nền, nhạc, sfx
# ---------------------------------------------------------------------------

def pick_background(duration: float, preferred: Optional[str] = None) -> tuple[Optional[Path], float]:
    """Chọn nền + điểm bắt đầu ngẫu nhiên.

    preferred = tên file người dùng chọn trong web; None = ngẫu nhiên, tránh trùng 3 lần render gần nhất.
    Không có nền → (None, 0).
    """
    bg_dir = media_dir("background")
    files = sorted(p for p in bg_dir.glob("*") if p.suffix.lower() in VIDEO_EXTS | IMAGE_EXTS)
    if not files:
        return None, 0.0
    history: list[dict] = read_json(HISTORY_PATH, []) or []
    recent = history[-3:]
    chosen = None
    if preferred:
        try:
            p = safe_media_path("background", preferred)
            chosen = p if p.exists() else None
        except ValueError:
            chosen = None
    if chosen is None:
        recent_files = {h.get("file") for h in recent}
        candidates = [f for f in files if f.name not in recent_files] or files
        chosen = random.choice(candidates)

    start = 0.0
    if chosen.suffix.lower() in VIDEO_EXTS:
        try:
            bg_len = ffprobe_duration(chosen)
        except RuntimeError:
            bg_len = 0.0
        span = max(0.0, bg_len - duration - 1.0)
        if span > 0:
            used = [h.get("start", 0) for h in recent if h.get("file") == chosen.name]
            for _ in range(20):  # cùng file thì chọn đoạn cách xa các lần trước
                start = random.uniform(0, span)
                if all(abs(start - u) > duration for u in used):
                    break
    history.append({"file": chosen.name, "start": round(start, 2), "at": int(time.time())})
    write_json(HISTORY_PATH, history[-20:])
    return chosen, start


MUSIC_HISTORY = LIBRARY_DIR / ".music_history.json"
NO_MUSIC = "__none__"


def music_files() -> list[Path]:
    """Nhạc trong thư mục nhạc nền (Cài đặt → Thư mục) + thư mục cũ library/music (tương thích bản trước)."""
    out: list[Path] = []
    for d in (media_dir("music"), MUSIC_DIR):
        if d.exists():
            out += [p for p in sorted(d.glob("*")) if p.is_file() and p.suffix.lower() in AUDIO_EXTS
                    and not p.name.startswith(".")]
    return out


def pick_music(preferred: Optional[str] = None) -> Optional[Path]:
    """preferred: tên file = dùng bài đó; NO_MUSIC = không nhạc; None = ngẫu nhiên (tránh lặp 2 bài gần nhất)."""
    if preferred == NO_MUSIC:
        return None
    files = music_files()
    if not files:
        return None
    if preferred:
        for p in files:
            if p.name == preferred:
                return p
    recent = [h.get("file") for h in (read_json(MUSIC_HISTORY, []) or [])[-2:]]
    pool = [p for p in files if p.name not in recent] or files
    chosen = random.choice(pool)
    write_json(MUSIC_HISTORY, ((read_json(MUSIC_HISTORY, []) or []) + [{"file": chosen.name, "at": int(time.time())}])[-20:])
    return chosen


def find_pop_sfx() -> Optional[Path]:
    for p in (LIBRARY_DIR / "sfx" / "pop.mp3", LIBRARY_DIR / "sfx" / "pop.wav",
              LIBRARY_DIR / "music" / "sfx" / "pop.mp3", LIBRARY_DIR / "music" / "sfx" / "pop.wav"):
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Âm thanh: giọng đọc + bụp
# ---------------------------------------------------------------------------

def _read_wav_mono(path: str | Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError(f"WAV không đúng định dạng 44.1 kHz mono 16-bit: {path}")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def _decode_to_wav(src: Path, dst: Path) -> Path:
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        run_ffmpeg(["-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(dst)])
    return dst


def _meme_video_audio(src: Path, duration: float, dst: Path) -> Optional[np.ndarray]:
    """Âm thanh đoạn đầu của meme video (None nếu video không có tiếng)."""
    if not has_audio(src):
        return None
    run_ffmpeg(["-t", f"{duration:.3f}", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-c:a", "pcm_s16le", str(dst)])
    data = _read_wav_mono(dst)
    fade = min(len(data), int(0.15 * SAMPLE_RATE))  # tắt dần ở cuối cho khỏi bị "bụp" khi cắt
    if fade:
        data = data.copy()
        data[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return data


def build_narration(part: dict, work: Path, sfx_volume: float, meme_video_audio: bool = True) -> Path:
    """Ghép giọng đọc từng câu đúng mốc thời gian + tiếng bụp (hoặc tiếng của meme video) → narration.wav."""
    total = int(math.ceil(part["duration"] * SAMPLE_RATE))
    buf = np.zeros(total, dtype=np.float32)
    for s in part["sentences"]:
        data = _read_wav_mono(s["wav"])
        i = int(round(s["start"] * SAMPLE_RATE))
        n = min(len(data), total - i)
        if n > 0:
            buf[i:i + n] += data[:n]
    pop_src = find_pop_sfx()
    if part["memes"] and sfx_volume > 0:
        pop = _read_wav_mono(_decode_to_wav(pop_src, work.parent / "_pop.wav")) if pop_src else None
        for k, m in enumerate(part["memes"]):
            clip = None
            src = media_dir("meme") / m["file"]
            if meme_video_audio and src.suffix.lower() in VIDEO_EXTS and src.exists():
                clip = _meme_video_audio(src, m["end"] - m["start"], work / f"meme_audio{k}.wav")
            if clip is None:
                clip = pop
            if clip is None:
                continue
            i = int(round(m["start"] * SAMPLE_RATE))
            n = min(len(clip), total - i)
            if n > 0:
                buf[i:i + n] += clip[:n] * float(sfx_volume)
    np.clip(buf, -1.0, 1.0, out=buf)
    out = work / "narration.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())
    return out


# ---------------------------------------------------------------------------
# Meme: dựng sẵn khung hình nảy
# ---------------------------------------------------------------------------

def _bounce_scale(t: float) -> float:
    """0 → 1,1 trong 0,18 s (ease-out), rồi 1,1 → 1,0 tới 0,3 s."""
    if t >= BOUNCE_DUR:
        return 1.0
    up = 0.18
    if t < up:
        p = t / up
        return TL.MEME_BOUNCE_MAX * (1 - (1 - p) ** 2)
    p = (t - up) / (BOUNCE_DUR - up)
    return TL.MEME_BOUNCE_MAX - (TL.MEME_BOUNCE_MAX - 1.0) * p


def _load_video_frames(path: Path, duration: float, tmp: Path) -> tuple[list[Image.Image], list[float]]:
    """Tách khung hình đoạn đầu của meme video (30 fps)."""
    tmp.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-t", f"{duration + 0.1:.3f}", "-i", str(path), "-an",
                "-vf", f"fps={FPS},scale=-2:'min({TL.MEME_H * 2},ih)'", "-pix_fmt", "rgba",
                str(tmp / "src%04d.png")])
    files = sorted(tmp.glob("src*.png"))
    if not files:
        raise RuntimeError(f"Không đọc được khung hình nào từ meme video {path.name}")
    frames = []
    for f in files:
        with Image.open(f) as im:
            frames.append(im.convert("RGBA"))
        f.unlink(missing_ok=True)
    return frames, [1.0 / FPS] * len(frames)


def _load_meme_frames(path: Path, duration: float = 3.0, tmp: Optional[Path] = None) -> tuple[list[Image.Image], list[float]]:
    if path.suffix.lower() in VIDEO_EXTS:
        return _load_video_frames(path, duration, tmp or path.parent / "_frames")
    with Image.open(path) as im:
        frames, durs = [], []
        for fr in ImageSequence.Iterator(im):
            frames.append(fr.convert("RGBA"))
            durs.append(max(0.02, (fr.info.get("duration") or im.info.get("duration") or 100) / 1000.0))
            if len(frames) >= 300:
                break
    return frames, durs


def prepare_meme_clip(meme_path: Path, duration: float, out_dir: Path) -> dict:
    """Tạo chuỗi PNG + file ffconcat cho một lần meme xuất hiện.

    Returns: {"list": path, "cw", "ch", "bw", "bh"} — kích thước khung (có chỗ cho 1,1×) và kích thước meme.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, durs = _load_meme_frames(meme_path, duration, out_dir / "_src")
    ow, oh = frames[0].size
    bh = TL.MEME_H
    bw = round(ow * bh / max(oh, 1))
    if bw > MEME_MAX_W:
        bw = MEME_MAX_W
        bh = round(oh * bw / max(ow, 1))
    cw = int(math.ceil(bw * TL.MEME_BOUNCE_MAX / 2) * 2)
    ch = int(math.ceil(bh * TL.MEME_BOUNCE_MAX / 2) * 2)
    scaled = [f.resize((bw, bh), Image.LANCZOS) for f in frames]
    anim_total = sum(durs)

    def src_at(t: float) -> int:
        if len(scaled) == 1:
            return 0
        t = t % anim_total
        acc = 0.0
        for i, d in enumerate(durs):
            acc += d
            if t < acc:
                return i
        return len(scaled) - 1

    # Các mốc thời gian cần một khung hình mới
    times: list[float] = []
    t = 0.0
    step = 1.0 / FPS
    while t < min(BOUNCE_DUR, duration):
        times.append(t)
        t += step
    fade_start = max(BOUNCE_DUR, duration - MEME_FADE_OUT)
    if len(scaled) > 1:
        acc = 0.0
        i = 0
        while acc < duration:
            if acc >= BOUNCE_DUR and acc < fade_start:
                times.append(acc)
            acc += durs[i % len(durs)]
            i += 1
    else:
        times.append(BOUNCE_DUR)
    t = fade_start
    while t < duration:
        times.append(t)
        t += step
    times = sorted({round(x, 4) for x in times if x < duration})

    entries: list[tuple[str, float]] = []
    cache: dict[tuple, str] = {}
    for k, t in enumerate(times):
        idx = src_at(t)
        s = _bounce_scale(t)
        alpha = 1.0
        if t >= fade_start and duration - fade_start > 0:
            alpha = max(0.0, 1.0 - (t - fade_start) / (duration - fade_start))
        key = (idx, round(s, 3), round(alpha, 2))
        if key not in cache:
            canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            w2, h2 = max(1, round(bw * s)), max(1, round(bh * s))
            if s > 0.02:
                fr = scaled[idx].resize((w2, h2), Image.BILINEAR) if (w2, h2) != (bw, bh) else scaled[idx]
                if alpha < 1.0:
                    a = fr.getchannel("A").point(lambda v: int(v * alpha))
                    fr = fr.copy()
                    fr.putalpha(a)
                canvas.alpha_composite(fr, ((cw - w2) // 2, (ch - h2) // 2))
            name = f"f{len(cache):04d}.png"
            canvas.save(out_dir / name, "PNG", compress_level=1)
            cache[key] = name
        nxt = times[k + 1] if k + 1 < len(times) else duration
        entries.append((cache[key], nxt - t))

    lines = ["ffconcat version 1.0"]
    for name, d in entries:
        lines += [f"file '{name}'", f"duration {max(d, 0.001):.4f}"]
    lines.append(f"file '{entries[-1][0]}'")  # concat demuxer bỏ qua duration của file cuối
    lst = out_dir / "list.ffconcat"
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"list": str(lst), "cw": cw, "ch": ch, "bw": bw, "bh": bh}


# ---------------------------------------------------------------------------
# Badge "Part N" / watermark
# ---------------------------------------------------------------------------

def render_badge(text: str, out_path: Path, font_size: int = 46, bg=(0, 0, 0, 150)) -> tuple[int, int]:
    from app.pipeline.card_render import load_font
    from PIL import ImageDraw
    font = load_font(font_size, bold=True)
    l, t, r, b = font.getbbox(text)
    pad_x, pad_y = 26, 14
    w, h = r - l + pad_x * 2, b - t + pad_y * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=bg)
    d.text((pad_x - l, pad_y - t), text, font=font, fill=(255, 255, 255, 240))
    img.save(out_path)
    return w, h


# ---------------------------------------------------------------------------
# Filter graph
# ---------------------------------------------------------------------------

def _build_piecewise(moves: list[dict]) -> str:
    """Biểu thức y(t) cho overlay: giữ nguyên → dịch chuyển (ease-out, 0,25 s) → giữ nguyên → ..."""
    A = TL.ANIM
    moves = sorted(moves, key=lambda m: m["t"])
    expr = str(moves[-1]["y1"])
    for i in range(len(moves) - 1, -1, -1):
        m = moves[i]
        T, y0, y1 = m["t"], m["y0"], m["y1"]
        p = f"(t-{T:.3f})/{A}"
        lerp = f"{y0}+({y1 - y0})*(1-(1-{p})*(1-{p}))"
        before = moves[i - 1]["y1"] if i > 0 else y0
        expr = f"if(lt(t,{T:.3f}),{before},if(lt(t,{T + A:.3f}),{lerp},{expr}))"
    return expr


def _ffmpeg_major() -> int:
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return 0
    m = re.search(r"ffmpeg version n?(\d+)\.", out)
    if m:
        return int(m.group(1))
    return 99 if re.search(r"ffmpeg version (N-|\d{4}-\d{2})", out) else 0


def build_command(part: dict, project_dir: Path, work: Path, cfg: dict, out_path: Path) -> tuple[list[str], str]:
    """Trả về (danh sách tham số ffmpeg không gồm 'ffmpeg', nội dung filter_complex)."""
    D = part["duration"]
    inputs: list[str] = []
    filters: list[str] = []
    idx = 0

    # --- Nền
    bg, bg_start = pick_background(D, cfg.get("background_file"))
    if bg is None:
        inputs += ["-f", "lavfi", "-i", f"color=c=0x1c1f2b:s={TL.VIDEO_W}x{TL.VIDEO_H}:r={FPS}"]
    elif bg.suffix.lower() in VIDEO_EXTS:
        inputs += ["-ss", f"{bg_start:.2f}", "-stream_loop", "-1", "-i", str(bg)]
    else:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(bg)]
    filters.append(
        f"[{idx}:v]scale={TL.VIDEO_W}:{TL.VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={TL.VIDEO_W}:{TL.VIDEO_H},setsar=1,fps={FPS},eq=brightness=-0.08,"
        f"trim=duration={D:.3f},setpts=PTS-STARTPTS[bg]"
    )
    idx += 1
    base = "bg"

    # --- Thẻ
    for k, c in enumerate(part["cards"]):
        img = project_dir / c["image"]
        if not img.exists():
            raise FileNotFoundError(f"Thiếu ảnh thẻ {c['image']}")
        inputs += ["-i", str(img)]
        dur = max(0.05, c["end"] - c["start"])
        chain = (f"[{idx}:v]scale={c['w']}:{c['h']}:flags=lanczos,format=rgba,"
                 f"loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB,trim=duration={dur:.3f},"
                 f"fade=t=in:st=0:d={TL.ANIM}:alpha=1")
        if c.get("fade_out_at") is not None:
            chain += f",fade=t=out:st={c['fade_out_at'] - c['start']:.3f}:d={TL.ANIM}:alpha=1"
        chain += f",setpts=PTS+{c['start']:.3f}/TB[c{k}]"
        filters.append(chain)
        out = f"vc{k}"
        filters.append(f"[{base}][c{k}]overlay=x={c['x']}:y='{_build_piecewise(c['moves'])}':eof_action=pass[{out}]")
        base = out
        idx += 1

    # --- Meme
    memes_dir = media_dir("meme")
    for k, m in enumerate(part["memes"]):
        src = memes_dir / m["file"]
        if not src.exists():
            continue
        dur = max(0.1, m["end"] - m["start"])
        clip = prepare_meme_clip(src, dur, work / f"meme{k}")
        inputs += ["-f", "concat", "-safe", "0", "-i", clip["list"]]
        x = (TL.VIDEO_W - clip["cw"]) // 2
        y = int(m["y"] - (clip["ch"] - clip["bh"]) / 2)
        y = max(0, min(y, TL.VIDEO_H - clip["ch"]))
        filters.append(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{m['start']:.3f}/TB[m{k}]")
        out = f"vm{k}"
        filters.append(f"[{base}][m{k}]overlay=x={x}:y={y}:eof_action=pass[{out}]")
        base = out
        idx += 1

    # --- Part N / watermark
    if part.get("index"):
        badge = work / "part_badge.png"
        bw, _ = render_badge(f"Part {part['index']}", badge)
        inputs += ["-i", str(badge)]
        filters.append(f"[{base}][{idx}:v]overlay=x={TL.VIDEO_W - bw - 40}:y=120[vpart]")
        base, idx = "vpart", idx + 1
    if cfg.get("watermark") and (cfg.get("channel_name") or "").strip():
        wm = work / "watermark.png"
        render_badge(cfg["channel_name"].strip(), wm, font_size=34, bg=(0, 0, 0, 90))
        inputs += ["-i", str(wm)]
        filters.append(f"[{base}][{idx}:v]overlay=x=40:y=120[vwm]")
        base, idx = "vwm", idx + 1
    filters.append(f"[{base}]format=yuv420p[vout]")

    # --- Âm thanh
    narration = build_narration(part, work, float(cfg.get("sfx_volume", 0.4)),
                                bool(cfg.get("meme_video_audio", True)))
    inputs += ["-i", str(narration)]
    voice_idx = idx
    idx += 1
    filters.append(f"[{voice_idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice]")
    music = pick_music(cfg.get("music_file"))
    vol = float(cfg.get("music_volume", 0.12))
    if music and vol > 0:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        filters.append(
            f"[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{D:.3f},asetpts=PTS-STARTPTS,volume={vol:.3f},"
            f"afade=t=out:st={max(0.0, D - 1.0):.3f}:d=1[music]")
        filters.append("[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]")
        idx += 1
        mix = "mix"
    else:
        mix = "voice"
    filters.append(f"[{mix}]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")

    filter_complex = ";\n".join(filters)
    script = work / "filter_complex.txt"
    script.write_text(filter_complex, encoding="utf-8")

    args = ["-hide_banner", "-y", "-progress", "pipe:1", "-nostats", *inputs]
    if _ffmpeg_major() >= 7:
        args += ["-/filter_complex", str(script)]
    else:
        args += ["-filter_complex_script", str(script)]
    args += [
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", H264_PRESET, "-crf", str(H264_CRF), "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{D:.3f}", str(out_path),
    ]
    meta = {"background": bg.name if bg else None, "background_start": round(bg_start, 2),
            "music": music.name if music else None}
    write_json(work / "render_info.json", meta)
    return args, filter_complex


def _run(args: list[str], duration: float, on_progress: Callable[[float], None] | None) -> None:
    require_binary("ffmpeg")
    proc = subprocess.Popen(["ffmpeg", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    err_lines: list[str] = []

    def _drain():
        for line in proc.stderr:  # type: ignore[union-attr]
            err_lines.append(line)
            if len(err_lines) > 200:
                del err_lines[:100]

    th = threading.Thread(target=_drain, daemon=True)
    th.start()
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.strip()
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                sec = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            if on_progress and duration > 0:
                on_progress(min(0.999, max(0.0, sec / duration)))
    proc.wait()
    th.join(timeout=5)
    if proc.returncode != 0:
        tail = "".join(err_lines[-25:]).strip()
        raise RuntimeError(f"FFmpeg render lỗi (mã {proc.returncode}):\n{tail[-1500:]}")


def render_part(part: dict, project_dir: Path, cfg: dict, out_path: Path,
                on_progress: Callable[[float], None] | None = None) -> Path:
    work = project_dir / "render" / (f"part{part['index']}" if part.get("index") else "main")
    if work.exists():
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    args, _ = build_command(part, project_dir, work, cfg, out_path)
    try:
        _run(args, part["duration"], on_progress)
    except RuntimeError as exc:
        if "-/filter_complex" in args and ("Unrecognized option" in str(exc) or "not found" in str(exc)):
            i = args.index("-/filter_complex")
            args[i] = "-filter_complex_script"
            _run(args, part["duration"], on_progress)
        else:
            raise
    return out_path


def render_timeline(timeline: dict, project_dir: Path, cfg: dict, on_progress: ProgressCb = None) -> list[Path]:
    """Render mọi Part. on_progress(phần_trăm_0_1, thông_điệp)."""
    parts = timeline["parts"]
    total = sum(p["duration"] for p in parts) or 1.0
    done = 0.0
    outputs: list[Path] = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for p in parts:
        name = f"output_part{p['index']}_{stamp}.mp4" if p.get("index") else f"output_{stamp}.mp4"
        out = project_dir / name
        label = f"Part {p['index']}" if p.get("index") else "video"

        def _cb(frac: float, _p=p, _done=done, _label=label):
            if on_progress:
                on_progress((_done + frac * _p["duration"]) / total, f"Đang render {_label}… {frac * 100:.0f}%")

        render_part(p, project_dir, cfg, out, _cb)
        done += p["duration"]
        outputs.append(out)
    if on_progress:
        on_progress(1.0, "Render xong")
    return outputs
