"""
Self-test: chạy toàn bộ pipeline với dữ liệu mẫu và xuất samples/out.mp4.

    python -m app.selftest            # dùng AI nếu đã nhập API key, Edge-TTS nếu có mạng
    python -m app.selftest --offline  # không gọi AI, không gọi Edge-TTS (giọng đọc giả bằng tiếng bíp)

Dữ liệu mẫu (tự sinh nếu chưa có) trong samples/: 2 ảnh chụp (ảnh 1 chứa 2 thẻ), 3 meme (1 GIF động),
1 video nền (FFmpeg testsrc2), 1 đoạn nhạc nền. Chạy cô lập trong samples/_work/, không đụng library/ thật.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
WORK = SAMPLES / "_work"

# Thư viện + dự án cô lập — phải đặt TRƯỚC khi import các module app.*
os.environ["TTV_LIBRARY_DIR"] = str(WORK / "library")
os.environ["TTV_PROJECTS_DIR"] = str(WORK / "projects")

SAMPLE_TEXTS = {
    "screenshot_1.png": [
        ("post", "Ở đời có một chân lý chua hơn bát canh dưa khú: cưới về rồi mới biết ai là người rửa bát."
                 "\nAnh ấy bảo 90% đàn ông biết nấu ăn, chỉ là không muốn nấu thôi."),
        ("post", "Thế là tôi để anh ấy nấu 3 bữa liền. Bữa đầu cháy nồi, bữa hai mặn chát, bữa ba thì gọi đồ ăn ngoài."
                 "\nGiờ anh ấy nói chân lý là phải chia việc cho công bằng!"),
    ],
    "screenshot_2.png": [
        ("comment", "Đọc xong cười muốn xỉu, nhà mình y chang vậy luôn, bữa ba gọi đồ ăn ngoài là chuẩn bài rồi."),
    ],
}

RESULTS: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""), flush=True)
    return ok


# ---------------------------------------------------------------------------
# Tạo dữ liệu mẫu
# ---------------------------------------------------------------------------

def _phone_screenshot(cards: list[tuple[str, str]], idx: int, out: Path) -> None:
    from PIL import Image, ImageDraw
    from app.pipeline.card_render import load_font, render_card_image

    W, H = 1080, 2340
    img = Image.new("RGB", (W, H), (30, 34, 48))
    d = ImageDraw.Draw(img)
    for y in range(H):  # nền tối kiểu game
        c = int(30 + 25 * math.sin(y / 180))
        d.line([(0, y), (W, y)], fill=(c, c + 8, c + 30))
    for i in range(14):
        x, y = (i * 173) % W, (i * 397) % H
        d.rectangle([x, y, x + 120, y + 120], fill=(60, 120 + i * 5 % 80, 70))
    d.rectangle([0, 0, W, 90], fill=(0, 0, 0))  # thanh trạng thái
    d.text((40, 24), "9:41", font=load_font(36, True), fill=(255, 255, 255))
    d.text((W - 160, 24), "100%", font=load_font(32), fill=(255, 255, 255))
    y = 260
    tmp = out.parent / "_tmp_card.png"
    for k, (kind, text) in enumerate(cards, start=1):
        render_card_image({"body": text, "kind": kind,
                           "display_name": "meomeo.official" if kind == "post" else "Người dùng 1",
                           "gray_avatar": kind == "comment", "time": "6 giờ",
                           "part_index": k if kind == "post" and len(cards) > 1 else None,
                           "part_total": len(cards) if kind == "post" and len(cards) > 1 else None}, tmp)
        card = Image.open(tmp).convert("RGB")
        card = card.resize((1000, round(card.height * 1000 / card.width)))
        img.paste(card, (40, y))
        y += card.height + 48
    tmp.unlink(missing_ok=True)
    img.save(out)


def _meme_face(out: Path, color, mouth: str, white_bg: bool = False) -> None:
    from PIL import Image, ImageDraw
    s = 400
    img = Image.new("RGBA", (s, s), (255, 255, 255, 255) if white_bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([20, 20, s - 20, s - 20], fill=color, outline=(40, 30, 10), width=8)
    d.ellipse([110, 120, 160, 190], fill=(40, 30, 10))
    d.ellipse([240, 120, 290, 190], fill=(40, 30, 10))
    if mouth == "smile":
        d.arc([100, 160, 300, 320], 15, 165, fill=(40, 30, 10), width=14)
    else:
        d.ellipse([160, 240, 240, 330], fill=(40, 30, 10))
    img.save(out)


def _meme_gif(out: Path) -> None:
    from PIL import Image, ImageDraw
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (360, 360), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        off = int(18 * math.sin(i / 8 * 2 * math.pi))
        d.ellipse([30, 30 + off, 330, 330 + off], fill=(120, 200, 255), outline=(20, 40, 80), width=8)
        d.line([(110, 150 + off), (160, 150 + off)], fill=(20, 40, 80), width=12)
        d.line([(200, 150 + off), (250, 150 + off)], fill=(20, 40, 80), width=12)
        d.line([(130, 250 + off), (230, 250 + off)], fill=(20, 40, 80), width=12)
        frames.append(img)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=90, loop=0, disposal=2)


def _music(out: Path, seconds: float = 6.0) -> None:
    import numpy as np
    sr = 44100
    t = np.arange(int(sr * seconds)) / sr
    sig = sum(np.sin(2 * np.pi * f * t) for f in (261.6, 329.6, 392.0)) / 3
    sig *= 0.3 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((sig * 32767).astype("int16").tobytes())


def ensure_samples() -> None:
    from app.utils import run_ffmpeg
    print("\n[2] Dữ liệu mẫu…")
    (SAMPLES / "memes").mkdir(parents=True, exist_ok=True)
    (SAMPLES / "backgrounds").mkdir(parents=True, exist_ok=True)
    (SAMPLES / "music").mkdir(parents=True, exist_ok=True)
    for name, cards in SAMPLE_TEXTS.items():
        p = SAMPLES / name
        if not p.exists():
            _phone_screenshot(cards, 0, p)
        step(f"Ảnh mẫu {name}", p.exists())
    memes = SAMPLES / "memes"
    if not (memes / "cuoi_tuoi.png").exists():
        _meme_face(memes / "cuoi_tuoi.png", (255, 214, 60), "smile")
    if not (memes / "soc_nang.png").exists():
        _meme_face(memes / "soc_nang.png", (255, 160, 90), "o", white_bg=True)
    if not (memes / "gat_gu.gif").exists():
        _meme_gif(memes / "gat_gu.gif")
    if not (memes / "bat_ngo.mp4").exists():  # meme dạng video có tiếng
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=480x360:rate=30:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=660:duration=2",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(memes / "bat_ngo.mp4")])
    step("4 meme mẫu (PNG, GIF động, video có tiếng)", len(list(memes.iterdir())) >= 4)
    bg = SAMPLES / "backgrounds" / "sample_bg.mp4"
    if not bg.exists():
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(bg)])
    step("Nền mẫu (FFmpeg testsrc2, 8 giây — ngắn hơn video để thử lặp)", bg.exists())
    music = SAMPLES / "music" / "sample_music.wav"
    if not music.exists():
        _music(music)
    step("Nhạc nền mẫu", music.exists())

    meta = {"memes": [
        {"file": "cuoi_tuoi.png", "name": "Cười tươi", "tags": ["hài hước", "vui", "cười"], "description": "Mặt vàng cười tươi"},
        {"file": "soc_nang.png", "name": "Sốc nặng", "tags": ["bất ngờ", "sốc", "hoảng"], "description": "Mặt cam há miệng sốc"},
        {"file": "gat_gu.gif", "name": "Gật gù", "tags": ["đồng tình", "cạn lời", "mỉa mai"], "description": "Mặt xanh gật gù"},
        {"file": "bat_ngo.mp4", "name": "Bất ngờ", "tags": ["bất ngờ", "sốc"], "description": "Video meme có tiếng bíp"},
    ], "texts": {k: [{"kind": a, "body": b} for a, b in v] for k, v in SAMPLE_TEXTS.items()}}
    (SAMPLES / "samples.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def setup_isolated_library() -> None:
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    lib = WORK / "library"
    for sub in ("memes", "backgrounds", "music", "sfx"):
        (lib / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLES / "backgrounds" / "sample_bg.mp4", lib / "backgrounds")
    shutil.copy2(SAMPLES / "music" / "sample_music.wav", lib / "music")
    real_pop = ROOT / "library" / "sfx" / "pop.mp3"
    if real_pop.exists():
        shutil.copy2(real_pop, lib / "sfx")
    (WORK / "projects").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Giọng đọc giả (khi offline)
# ---------------------------------------------------------------------------

def install_fake_tts() -> None:
    """Thay TTS bằng tiếng bíp dài theo số chữ — để test được khi không có mạng."""
    import numpy as np
    import app.pipeline.tts as tts_pkg
    from app.pipeline.tts.base import TTSBase

    class BeepTTS(TTSBase):
        name = "beep"
        output_ext = ".wav"

        async def synthesize(self, text, output_path, voice, speed):
            sr = 24000
            dur = max(0.8, len(text.split()) * 0.28)
            t = np.arange(int(sr * dur)) / sr
            sig = 0.25 * np.sin(2 * np.pi * 440 * t) * (np.sin(2 * np.pi * 3 * t) > 0)
            with wave.open(output_path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes((sig * 32767).astype("int16").tobytes())

    tts_pkg.get_tts = lambda cfg: BeepTTS()


# ---------------------------------------------------------------------------
# Kiểm tra
# ---------------------------------------------------------------------------

def check_dependencies() -> bool:
    print("[1] Kiểm tra thư viện và FFmpeg…")
    ok = True
    for mod, pkg in [("fastapi", "fastapi"), ("PIL", "Pillow"), ("cv2", "opencv-python-headless"),
                     ("numpy", "numpy"), ("edge_tts", "edge-tts")]:
        try:
            __import__(mod)
            step(f"import {mod}", True)
        except ImportError:
            ok = step(f"import {mod}", False, f"pip install {pkg}") and ok
    for b in ("ffmpeg", "ffprobe"):
        path = shutil.which(b)
        ok = step(b, bool(path), path or "chưa cài / chưa có trong PATH") and ok
    return ok


def _probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def _similarity(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, " ".join(a.split()), " ".join(b.split())).ratio()


async def run_pipeline(offline: bool) -> bool:
    from app.config import get_config, has_llm
    from app.pipeline import memes as meme_lib
    from app.pipeline import project as P

    cfg = get_config()
    cfg["auto_mode"] = True
    use_ai = has_llm(cfg) and not offline

    print("\n[3] Cắt thẻ từ ảnh…")
    proj = P.create_project()
    pid = proj["id"]
    files = [(n, (SAMPLES / n).read_bytes()) for n in SAMPLE_TEXTS]
    data = P.add_images(pid, files)
    by_src: dict[str, int] = {}
    for c in data["cards"]:
        by_src[c["source_image"]] = by_src.get(c["source_image"], 0) + 1
    n1 = by_src.get("input/screenshot_1.png", 0)
    n2 = by_src.get("input/screenshot_2.png", 0)
    step("Ảnh có 2 thẻ được cắt thành 2 thẻ", n1 == 2, f"screenshot_1 → {n1} thẻ")
    step("Ảnh có 1 thẻ được cắt thành 1 thẻ", n2 == 1, f"screenshot_2 → {n2} thẻ")
    from app.pipeline.crop import detect_author_regions
    from app.utils import imread
    pdir0 = WORK / "projects" / pid
    found = []
    for c in data["cards"]:
        img = imread(pdir0 / c["image"])
        regs = detect_author_regions(img)
        body_top = 0.12 * img.shape[1]  # thân bài bắt đầu dưới dòng tên
        found.append(len(regs) == 2 and all(r[3] <= body_top for r in regs[1:]) and regs[0][0] < 0.1 * img.shape[1])
    step("Dò đúng avatar + dòng tên để che (không đụng thân bài)", all(found), f"{sum(found)}/{len(found)} thẻ")

    print("\n[4] Đọc chữ (OCR)…")
    expected = [t for n in SAMPLE_TEXTS for t in SAMPLE_TEXTS[n]]
    if use_ai:
        try:
            data = await P.run_ocr(pid, cfg)
            for c, (_, body) in zip(data["cards"], expected):
                sim = _similarity(c["body"], body)
                step(f"OCR {c['card_id']} ({c['kind']})", sim > 0.85, f"giống {sim * 100:.0f}% so với chữ gốc")
        except Exception as exc:
            step("OCR bằng AI", False, str(exc))
            use_ai = False
    if not use_ai:
        edits = {c["card_id"]: {"body": body, "kind": kind}
                 for c, (kind, body) in zip(data["cards"], expected)}
        data = P.update_cards(pid, edits=edits)
        step("OCR", True, "bỏ qua AI — dùng chữ mẫu có sẵn" + (" (--offline)" if offline else " (chưa có API key)"))

    print("\n[5] Thư viện meme…")
    meta = json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8"))["memes"]
    for m in meta:
        meme_lib.add_meme(m["file"], (SAMPLES / "memes" / m["file"]).read_bytes())
        meme_lib.update_meme(m["file"], m)
    try:
        meme_lib.remove_white_background("soc_nang.png")
        step("Xóa nền trắng meme", (WORK / "library" / "memes" / "soc_nang.png").exists())
    except Exception as exc:
        step("Xóa nền trắng meme", False, str(exc))
    step(f"Nạp {len(meta)} meme", len(meme_lib.list_memes()) == len(meta))

    print("\n[6] Lên kế hoạch…")
    if not use_ai:
        cfg = {**cfg, "gemini_api_key": "", "claude_api_key": "", "openai_api_key": ""}
    plan, warning = await P.make_plan(pid, cfg)
    sents = [s for c in plan["cards"] for s in c["sentences"]]
    with_meme = [i for i, s in enumerate(sents) if s["meme"]]
    step("Plan có câu", len(sents) > 0, f"{len(sents)} câu, {len(with_meme)} meme" + (f" — {warning}" if warning else ""))
    step("Câu đầu không có meme", not sents[0]["meme"])
    step("Không 2 câu liền nhau đều có meme", all(b - a >= 2 for a, b in zip(with_meme, with_meme[1:])))
    bad = [s["speak_text"] for s in sents if any(x in s["speak_text"] for x in ("*", "1/2", "2/2", "90%"))]
    step("speak_text không chứa *, x/y, ký hiệu %", not bad, "; ".join(bad[:2]))
    step("Có câu chuyển cảnh trước bình luận", bool(plan.get("transition_before_comments")))
    # Bảo đảm render thử đủ 3 loại meme: ảnh PNG, GIF động, video có tiếng (vẫn đúng luật cách câu)
    for s in sents:
        s["meme"] = None
    for slot, file in zip(range(2, len(sents), 2), ["cuoi_tuoi.png", "gat_gu.gif", "bat_ngo.mp4"]):
        sents[slot]["meme"] = file
    P.save_plan(pid, plan)
    P.set_background(pid, "sample_bg.mp4")

    print("\n[7] Giọng đọc…")
    if offline:
        install_fake_tts()
        step("TTS", True, "dùng tiếng bíp giả (--offline)")
    else:
        from app.pipeline.tts import synthesize_cached
        try:
            _, dur = await synthesize_cached("Xin chào, đây là bài kiểm tra.", cfg)
            step("Edge-TTS", dur > 0.5, f"{dur:.2f} giây")
        except Exception as exc:
            step("Edge-TTS", True, f"không dùng được ({exc}) → chuyển sang tiếng bíp giả")
            install_fake_tts()

    print("\n[8] Render…")
    t0 = time.time()
    last = [-1]

    def progress(frac, msg):
        pct = int(frac * 100)
        if pct // 10 != last[0] // 10:
            print(f"     {pct:3d}%  {msg}", flush=True)
        last[0] = pct

    try:
        result = await P.render_project(pid, cfg, progress)
    except Exception as exc:
        step("Render", False, str(exc)[-800:])
        return False
    elapsed = time.time() - t0
    pdir = WORK / "projects" / pid
    outputs = [pdir / o["file"] for o in result["outputs"]]
    final = SAMPLES / "out.mp4"
    shutil.copy2(outputs[0], final)
    for i, o in enumerate(outputs[1:], start=2):
        shutil.copy2(o, SAMPLES / f"out_part{i}.mp4")
    step("Render", final.exists(), f"{result['duration']:.1f} giây video trong {elapsed:.1f} giây "
                                   f"({result['duration'] / max(elapsed, 0.01):.2f}× thời gian thực)")

    print("\n[9] Kiểm tra file xuất…")
    info = _probe(final)
    v = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), {})
    a = next((s for s in info.get("streams", []) if s["codec_type"] == "audio"), {})
    step("Video H.264 1080×1920 30fps", v.get("codec_name") == "h264" and v.get("width") == 1080
         and v.get("height") == 1920 and v.get("r_frame_rate") == "30/1",
         f"{v.get('codec_name')} {v.get('width')}×{v.get('height')} {v.get('r_frame_rate')}")
    step("Âm thanh AAC", a.get("codec_name") == "aac", a.get("codec_name", "không có"))
    tl = json.loads((pdir / "timeline.json").read_text(encoding="utf-8"))
    part = tl["parts"][0]
    dur = float(info.get("format", {}).get("duration", 0))
    step("Độ dài khớp timeline (lệch < 0,1 s)", abs(dur - part["duration"]) < 0.1,
         f"file {dur:.3f}s / timeline {part['duration']:.3f}s")
    first = {}
    for s in part["sentences"]:
        first.setdefault(s["card_id"], s["start"])
    sync = all(abs(c["start"] - first[c["card_id"]]) < 0.1 for c in part["cards"])
    step("Thẻ xuất hiện đúng lúc bắt đầu đọc", sync)
    step("Tối đa 2 thẻ cùng lúc", max(
        sum(1 for c in part["cards"] if c["start"] <= t < c["end"] - 0.25)
        for t in [x / 10 for x in range(int(part["duration"] * 10))]) <= 2)
    used = {m["file"] for p in tl["parts"] for m in p["memes"]}
    step("Render đủ meme ảnh, GIF và video", {"cuoi_tuoi.png", "gat_gu.gif", "bat_ngo.mp4"} <= used, ", ".join(sorted(used)))
    step("Dùng đúng video nền đã chọn", result.get("background") == "sample_bg.mp4", str(result.get("background")))

    print("\n[10] Duyệt & lưu…")
    ap = P.approve(pid)
    approved_dir = WORK / "library" / "approved"
    ok = all((approved_dir / f).exists() and (approved_dir / f).with_suffix(".txt").exists() for f in ap["files"])
    step("Lưu vào thư mục video đã duyệt (kèm .txt caption)", ok, ", ".join(ap["files"]))
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Self-test pipeline dựng video Threads")
    ap.add_argument("--offline", action="store_true", help="không gọi AI và Edge-TTS")
    ap.add_argument("--keep", action="store_true", help="giữ lại thư mục samples/_work để xem file tạm")
    args = ap.parse_args()

    print("=" * 64 + "\n  SELF-TEST — Tool dựng video Threads\n" + "=" * 64)
    if not check_dependencies():
        print("\n⚠️  Thiếu thư viện hoặc FFmpeg. Cài đặt rồi chạy lại.")
        sys.exit(1)

    from app import assets
    assets.ensure_dirs()
    assets.ensure_pop_sfx()
    assets.ensure_fonts()
    ensure_samples()
    setup_isolated_library()
    ok = asyncio.run(run_pipeline(args.offline))
    if not args.keep:
        shutil.rmtree(WORK, ignore_errors=True)

    passed = sum(1 for _, o, _ in RESULTS if o)
    print("\n" + "=" * 64)
    print(f"  {passed}/{len(RESULTS)} bước đạt")
    failed = [n for n, o, _ in RESULTS if not o]
    if ok and not failed:
        print("  🎉 Pipeline hoạt động! File xuất: samples/out.mp4")
        sys.exit(0)
    print("  ❌ Chưa đạt: " + ", ".join(failed))
    sys.exit(1)


if __name__ == "__main__":
    main()
