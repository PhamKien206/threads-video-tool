# Threads Video Tool 🎬

A web app that runs on your own computer and builds vertical 9:16 videos in the style of
**"reading a Threads post over gameplay footage, with reaction memes"**.
Upload screenshots of a Threads post **or** paste a link, click a button, and get a 1080×1920 MP4.

> The app's interface is in Vietnamese and the voice-over is Vietnamese. This README gives the
> Vietnamese button and folder names exactly as they appear in the app, followed by their English meaning.

- Gameplay footage plays for the whole video (muted, slightly darkened). It is picked at random and won't repeat any of the last 3 videos.
- Post cards appear one by one in the top half, at most 2 on screen. When a 3rd card comes in, the first one slides up and disappears.
- The Vietnamese voice-over **reads only the post body**: not names, timestamps, "1/7" counters or `*` characters. Each card appears exactly when its text starts being read.
- AI picks a meme for each sentence based on its emotion. Memes pop up with a "pop" sound effect. Background music plays at 12% volume under the voice-over.
- Videos longer than 90 seconds are automatically split into **Part 1, Part 2…**, with a "Part N" label in the corner.
- Suggests a title, caption and hashtags for posting.
- **4 folders you control**: `nen_video/` (background gameplay videos), `meme/` (meme images, GIFs and videos),
  `nhac_nen/` (background music) and `video_da_duyet/` (videos you approve). The app picks backgrounds, memes and music straight from these folders.
- Flexible AI: **Gemini, Claude, OpenAI, Z.ai or OpenRouter** (API key required), or **Ollama running locally** (no key needed), with an optional fallback provider.

## Contents

1. [Installation](#1-installation-on-windows-1011)
2. [Getting an AI API key](#2-getting-an-ai-api-key) · [Local AI with Ollama](#local-ai-with-ollama-no-api-key)
3. [Folders: backgrounds, memes, music, approved videos](#3-folders-backgrounds-memes-music-approved-videos)
4. [Making a video](#4-making-a-video)
5. [Self-test](#5-self-test)
6. [Project structure](#6-project-structure)
7. [FAQ](#7-faq)

### Quick start

```bash
git clone <this-repo-url> && cd <repo-folder>
# Windows: double-click run.bat   ·   macOS/Linux:
chmod +x run.sh && ./run.sh
# → open http://localhost:8000, choose an AI in Cài đặt (Settings),
#   copy background videos into nen_video/ and memes into meme/
```

`config.json` is created automatically on first run and is **never committed to Git** (it contains your API keys).

---

## 1. Installation on Windows 10/11

No GPU is needed. An internet connection is needed for the Edge-TTS voice and the AI.

### Step 1: Install Python 3.11 or newer
Download it from <https://www.python.org/downloads/>. During installation, **check "Add Python to PATH"**.

### Step 2: Install FFmpeg
The fastest way: open **PowerShell** and run

```powershell
winget install Gyan.FFmpeg
```

Or install it manually: download the *release full* build from <https://www.gyan.dev/ffmpeg/builds/>, extract it
(for example to `C:\ffmpeg`), then add `C:\ffmpeg\bin` to the **Path** environment variable
(Start → type "environment variables" → Path → New).

Close all command-line windows, open a new one and check: `ffmpeg -version`.

### Step 3: Run the tool
Double-click **`run.bat`**. On first run the script will:
1. create a `.venv` virtual environment and install the packages in `requirements.txt`;
2. install the Chromium browser for Playwright (`playwright install chromium`), which is used for pasting Threads links;
3. open your browser at **<http://localhost:8000>**.

Keep that black console window open while you use the tool. Press `Ctrl+C` to stop it.

### macOS / Linux

```bash
# macOS
brew install python@3.11 ffmpeg
# Ubuntu/Debian
sudo apt install python3.11 python3.11-venv ffmpeg

chmod +x run.sh && ./run.sh
# Linux: if pasting a link complains about missing system libraries:
sudo .venv/bin/playwright install-deps chromium
```

### Docker

```bash
docker build -t threads-video .
docker run -p 8000:8000 -v "$PWD/nen_video:/app/nen_video" -v "$PWD/meme:/app/meme" \
  -v "$PWD/nhac_nen:/app/nhac_nen" -v "$PWD/video_da_duyet:/app/video_da_duyet" \
  -v "$PWD/projects:/app/projects" threads-video
```

### Installing Playwright manually (if needed)

```bash
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install playwright
playwright install chromium
```

---

## 2. Getting an AI API key

The AI reads text from screenshots, splits it into sentences, picks memes, filters comments and suggests captions.
Choose **one** provider, or use Ollama on your own machine with no key (see [Local AI with Ollama](#local-ai-with-ollama-no-api-key)):

| Provider | Get a key | Notes |
|---|---|---|
| **Gemini** (recommended) | <https://aistudio.google.com/app/apikey> → *Create API key* | Free daily quota |
| **Claude** | <https://console.anthropic.com/settings/keys> → *Create Key* | Pay as you go |
| **OpenAI** | <https://platform.openai.com/api-keys> → *Create new secret key* | Pay as you go |
| **Z.ai (GLM)** | The *API Keys* page on z.ai | Pay per token, very cheap |
| **OpenRouter** | <https://openrouter.ai/keys> | Free `:free` models (rate-limited) |

Open **Cài đặt** (Settings, <http://localhost:8000/settings>) → choose a provider → paste the key →
**Lưu & kiểm tra kết nối AI** (Save & test AI connection).

- The key is stored only in `config.json` on your computer. After saving, it is shown only as `****abcd`. Don't share this file.
- Leave the **Model** field empty to use the default model (Gemini `gemini-3.8-flash`, Claude `claude-sonnet-5-5`, OpenAI `gpt-4o-mini`, Z.ai `glm-5.3-flash`, OpenRouter `z-ai/glm-5.3-flash:free`).
- **Z.ai (GLM):** create a key on z.ai's API Keys page and top up under **Billing** (pay per token, about 0.002–0.003 USD per video). You do NOT need the GLM Coding Plan; that plan is only for coding tools.
- **OpenRouter:** create a key at openrouter.ai/keys. Models ending in `:free` (e.g. `z-ai/glm-5.3-flash:free`) cost nothing but are rate-limited. On a 429 error the tool waits 20 seconds and retries up to 3 times.
- **OpenAI Base URL:** leave empty for OpenAI. Enter another URL to use any OpenAI-compatible service.
- **Fallback:** choose a second provider (with its key entered). When the main provider runs out of credit, hits its quota or is rate-limited, the tool switches to the fallback automatically. Example: main = Gemini (free), fallback = Z.ai.
  You can also enter a different model, such as a cheaper model from the same provider.
- With Claude, the tool enables server-side *fallback*: if the main model refuses content because of a safety filter,
  Anthropic automatically reruns the request on the fallback model (billed at the fallback model's price).
- **It still works without a key**: you type the text for each card yourself, sentences are split by rules and memes are picked at random.

### Local AI with Ollama (no API key)

Works well on a machine with a 6 GB NVIDIA card such as a **GTX 1660 Ti** and 16 GB of RAM.

1. Download and install **Ollama** from https://ollama.com/download, then open it (the llama icon in the system tray).
2. In the tool: **Cài đặt → AI → 🖥️ Máy này (Ollama)** (Settings → AI → This machine). The tool checks Ollama automatically.
3. Click **⬇ Tải** (Download) next to `qwen3.5:4b` (about 3.4 GB, downloaded once). This one model handles **reading text from images**, as well as **splitting sentences, picking memes, filtering comments and writing captions**.
4. Click **Lưu & kiểm tra kết nối AI** (Save & test AI connection). When you see "Chạy 100% trên card đồ họa ✅" (running 100% on the GPU), you're done.

Tips:
- The first call takes 10–30 seconds to load the model onto the GPU. Later calls are fast (the model stays loaded for 15 minutes).
- If it says "đang chạy bằng CPU" (running on CPU), update your NVIDIA driver and restart Ollama.
- You can set **Fallback = Máy này (Ollama)** while using Gemini: when the Gemini quota runs out, the tool switches to the local AI.
- If Ollama is off or not installed, sentence splitting and meme picking still work in **no-AI mode** (memes are picked by emotion keywords). Reading text from images needs an AI, or you can type the card text yourself.

---

## 3. Folders: backgrounds, memes, music, approved videos

| Folder (default, inside the tool folder) | Contents |
|---|---|
| `nen_video/` (background videos) | Gameplay videos used as the background (MP4/MOV/MKV/WebM). The tool crops them to 9:16, darkens them slightly, mutes them, starts at a random point and loops them if they're short. |
| `meme/` | Memes as images (PNG with a transparent background is best, JPG, WebP), animated GIFs or **short videos** (MP4/WebM/MOV). Video memes play with their own sound. |
| `nhac_nen/` (background music) | Background music (MP3, WAV, M4A, OGG, FLAC). See [Background music](#background-music). |
| `video_da_duyet/` (approved videos) | Videos you approve with **✅ Duyệt & lưu** (Approve & save) after rendering, each with a `.txt` file of the same name containing the title, caption and hashtags. |

- Just **copy files straight into the folder** with File Explorer (then click "↻ Làm mới" (Refresh) in the app), or drag and drop them on the **Thư viện** (Library) page.
  Background videos can be several GB, so copy them into the folder directly.
- To use a folder somewhere else (for example `D:\Video\Gameplay`): **Cài đặt → 📁 Thư mục** (Settings → Folders), then enter the full path.
- When creating a video, use **🎮 Video nền** (Background video) in step 1 or in the review step: choose 🎲 *Ngẫu nhiên* (Random, won't repeat the last 3) or a specific video.
  The AI picks memes from the `meme/` folder. In the review step, click a sentence's meme cell to change it (with thumbnails; videos are marked ▶).

Also: the "pop" sound played when a meme appears is `library/sfx/pop.mp3` (you can replace it).

The **Thư viện** (Library) page (<http://localhost:8000/memes>) has a tab for each folder, and each tab has a **📂 Mở thư mục** (Open folder) button:
- Drag and drop meme images/GIFs/videos and background videos.
- **🤖 AI gắn nhãn** (AI tagging): the AI looks at the image and fills in a name, description and emotion tags (in Vietnamese, e.g. `khinh bỉ, mỉa mai, cạn lời…`, meaning contempt, sarcasm, speechless). There's also a button to tag all untagged memes at once.
- **✨ Xóa nền trắng** (Remove white background, still images only): turns the white background around a meme transparent. It flood-fills from the 4 corners, so white areas inside the image such as eyes and teeth are kept.
- **Video đã duyệt** (Approved videos) tab: watch, download, or open the caption file.
- The AI picks memes based on their name, tags and description, so the clearer the emotion tags, the better the memes fit.

### Background music

- Copy music files (MP3, WAV, M4A, OGG, FLAC) into the **`nhac_nen`** folder (changeable in Settings → Folders), or upload them under **Thư viện → 🎵 Nhạc nền** (Library → Background music).
- When creating a video, choose music in step 1 or the review step: **🎲 Ngẫu nhiên** (Random, avoids the last 2 tracks), **🔇 Không nhạc** (No music), or a specific track (click ▶ to preview).
- Music plays quietly under the voice-over (volume is set in Settings), loops if it's shorter than the video and fades out at the end. A video split into several parts uses the same track for all of them.
- The repo doesn't include any music. Use royalty-free music from the YouTube Audio Library or Pixabay Music to avoid videos being taken down.

---

## 4. Making a video

### Option 1: Upload screenshots
1. Home page → **Upload ảnh chụp** (Upload screenshots) → drag and drop images → **Cắt thẻ từ ảnh** (Crop cards from images).
   A screenshot containing several cards is split into separate cards. The phone status bar, black borders and game background are removed.
2. The AI reads the text of each card, automatically hides the names and avatars of **commenters**
   (the original author has a separate toggle in Settings), and orders the cards by "1/7, 2/7…" numbering if present.
3. In the **Thẻ** (Cards) step: drag ⠿ to reorder, fix the text if the AI misread it, switch the type between
   *Bài gốc / Bình luận* (Original post / Comment), use **✂ Cắt lại** (Re-crop) if a card was cropped wrong,
   or click the original image to draw a box and crop an extra card.

### Option 2: Paste a Threads link
Paste a link like `https://www.threads.com/@name/post/...` (`threads.net` also works) → **Lấy bài và bình luận** (Fetch post and comments).
The tool fetches the author's whole 1/N thread and filters out junk comments (only @tags, only emoji, containing links,
under 5 or over 80 words, duplicates). The AI then picks 3–6 good, varied comments, and the tool draws Threads-style
cards itself, with commenters shown as "Người dùng 1, 2…" (User 1, 2…).
Without logging in you usually get about the first 20 comments. You can enter a cookie (this carries some risk; see the warning in the app).
If Threads blocks the request, the tool shows an error and suggests uploading screenshots instead.

### Review and render
- **Lên kế hoạch** (Plan) → review table: each sentence has its *display text*, its *spoken text* (numbers and
  abbreviations written out as words, editable), a meme (click to choose from a list with thumbnails, or "Không" (None)),
  and a ▶ button to **preview the voice**.
- **Render video** → watch the progress → preview, download the MP4, copy the title / caption / hashtags.
- When you're happy with it, click **✅ Duyệt & lưu** (Approve & save). The video is copied into `video_da_duyet/`
  (the file name includes the date, time and title) together with a `.txt` caption file.
- **Edit the plan and re-render**: voice clips are cached by (sentence + voice + speed), so only the sentences you changed are regenerated.
- The **Tự động hoàn toàn** (Fully automatic) switch in the top corner skips the review step: one click in step 1 produces the video.

### Meme rules (always enforced, even if the AI forgets)
The first sentence of a video never has a meme · no two consecutive sentences both have memes · each meme appears at most twice per video ·
density *Ít* (Low, about 1 meme per card), *Vừa* (Medium, about 1 meme every 2–3 sentences), *Nhiều* (High, about 1 meme every 1–2 sentences).
A meme appears at the start of its sentence and stays for `max(1.5, min(2.5, sentence length))` seconds.

---

## 5. Self-test

```bash
python -m app.selftest            # uses the AI if a key is set, and Edge-TTS if online
python -m app.selftest --offline  # no AI or Edge-TTS calls (the voice is replaced by beeps)
```

Runs the full real pipeline (crop cards → read text → plan → voice-over → timeline → render) on the sample data in
`samples/`: 2 screenshots (the first contains 2 cards), 3 memes (including 1 animated GIF), 1 background video generated
with FFmpeg's `testsrc2`, and 1 music clip.
Output: `samples/out.mp4`, plus checks that exactly 2 cards were cropped, the meme rules hold, the duration, resolution and
codec are correct, and the cards line up with the voice-over.
The self-test runs inside `samples/_work/` and doesn't touch your real library.

---

## 6. Project structure

```
app/
  main.py              FastAPI: web pages + API, background render jobs, progress via SSE
  config.py            reads/writes config.json
  assets.py            creates folders, downloads fonts, generates the "pop" sound on first run
  selftest.py          python -m app.selftest
  llm/                 base.py (retries + resends when JSON doesn't match the schema), gemini.py, claude.py,
                       openai_llm.py, ollama.py (local AI), factory.py (picks the provider + fallback)
  pipeline/
    crop.py            crops cards from screenshots, manual crop, hides name areas
    ocr.py             AI text reading (prompt B1)
    threads_fetch.py   fetches the post + comments from a link (Playwright)
    comment_filter.py  junk filtering + AI comment selection (prompt B3), anonymisation
    planner.py         AI sentence splitting + meme picking (prompt B2), re-checks the meme rules
    textnorm.py        normalises text for reading aloud (numbers → words, abbreviations, strips * / emoji / "1/7")
    card_render.py     draws Threads-style cards
    tts/               base.py, edge.py, vieneu.py (same interface) + cache
    timeline.py        timings, card/meme layout, splitting into parts
    render.py          builds the FFmpeg command (filter_complex)
    memes.py           meme library, AI tagging (B4), white background removal
    media.py           the user folders: listing, thumbnails, opening folders
    caption.py         caption suggestions (B5)
    project.py         orchestrates a single project
  prompts/             ocr.md (B1), planner.md (B2), comment_filter.md (B3), meme_tagger.md (B4), caption.md (B5)
  fonts/               Be Vietnam Pro (OFL licence)
  static/              index.html, memes.html, settings.html, css/, js/
nen_video/             background gameplay videos (changeable in Settings)
meme/                  meme images / GIFs / videos (changeable in Settings)
nhac_nen/              background music (changeable in Settings)
video_da_duyet/        approved videos + .txt caption files (changeable in Settings)
library/               memes.json (meme tags) · sfx/pop.mp3 · music/background pick history
projects/<id>/         input/, cards/, plan.json, timeline.json, output_*.mp4 for each video
cache/tts/             generated voice clips (safe to delete; they'll be regenerated)
samples/               data for the self-test
config.json            settings (contains API keys — do not share)
```

The AI prompts live in `app/prompts/*.md` and are loaded at runtime, so editing a file takes effect immediately with no code changes.

---

## 7. FAQ

**"Không tìm thấy ffmpeg" (ffmpeg not found)**: Install FFmpeg (section 1), then **reopen** your command-line window so it picks up the new PATH.

**"API key … không hợp lệ" (invalid API key) / "hết quota" (quota exceeded)**: Check the key in Settings. Free Gemini has per-minute and per-day limits, so wait and try again.

**Voice error "Edge-TTS không tạo được giọng đọc" (Edge-TTS couldn't generate the voice)**: Edge-TTS needs internet access, and Microsoft's
servers occasionally reject a sentence for a while (especially under rapid-fire requests). The tool already retries 7 times with
increasing delays. If it still fails, wait a moment and click **↻ Thử lại** (Retry); sentences that already finished are kept in the cache.

**Can't fetch the post from a link**: Threads changes its layout and blocks automated access often. Try again later, use a cookie
(Settings → Threads), or take screenshots and use the upload option. If it says Chromium is missing, run `playwright install chromium`.

**Cards are cropped wrong**: Click **✂ Cắt lại** (Re-crop) on that card and drag the box, or click the original image to crop an
extra card. The algorithm looks for large white/light background areas, so dark-mode screenshots usually need manual cropping.

**VieNeu-TTS (offline voice)**: Not installed by default because it's large. Try `pip install vieneu` inside `.venv`, then select it in Settings.
This integration is experimental: if the library version has a different API, the tool shows a clear error. In that case use Edge-TTS.

**How long does rendering take?** The video rendering itself runs faster than real time on a typical CPU (a 60-second video takes
about 30–60 seconds). The first time, add the time needed to generate the voice-over online.

---

Be Vietnam Pro font © The Be Vietnam Pro Project Authors, SIL Open Font License 1.1 (`app/fonts/OFL.txt`).
