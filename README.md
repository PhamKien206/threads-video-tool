# Tool dựng video Threads 🎬

Web app chạy trên máy bạn, tự dựng video dọc 9:16 kiểu **"đọc bài Threads trên nền gameplay, có meme phản ứng"**:
upload ảnh chụp bài Threads **hoặc** dán link → bấm nút → ra file MP4 1080×1920.

- Nền gameplay chạy suốt video (tắt tiếng, tối nhẹ), chọn ngẫu nhiên, không trùng 3 lần gần nhất.
- Thẻ bài hiện lần lượt ở nửa trên, tối đa 2 thẻ cùng lúc; thẻ thứ 3 vào thì thẻ đầu trượt lên và biến mất.
- Giọng đọc tiếng Việt **chỉ đọc thân bài** (không đọc tên, thời gian, "1/7", dấu `*`). Thẻ hiện đúng lúc bắt đầu đọc.
- AI chọn meme theo cảm xúc từng câu; meme nảy lên kèm tiếng "bụp". Nhạc nền 12% dưới giọng đọc.
- Dài hơn 90 giây thì tự chia **Part 1, Part 2…** (có chữ "Part N" ở góc).
- Gợi ý tiêu đề, caption và hashtag để đăng bài.
- **4 thư mục của bạn**: `nen_video/` (video gameplay làm nền), `meme/` (ảnh, GIF, video meme), `nhac_nen/` (nhạc nền),
  `video_da_duyet/` (video bạn bấm duyệt). Trong web chọn nền, meme, nhạc lấy thẳng từ các thư mục này.
- AI linh hoạt: **Gemini, Claude, OpenAI, Z.ai, OpenRouter** (cần API key) hoặc **Ollama chạy trên máy** (không cần key), có nhà cung cấp dự phòng.

## Mục lục

1. [Cài đặt](#1-cài-đặt-trên-windows-1011)
2. [Lấy API key AI](#2-lấy-api-key-ai) · [AI chạy trên máy (Ollama)](#️-ai-chạy-trên-máy-không-cần-api-key--ollama)
3. [Các thư mục: video nền, meme, video đã duyệt](#3-các-thư-mục-video-nền-meme-video-đã-duyệt) · [Nhạc nền](#-nhạc-nền)
4. [Làm video](#4-làm-video)
5. [Kiểm tra nhanh (self-test)](#5-kiểm-tra-nhanh-self-test)
6. [Cấu trúc thư mục](#6-cấu-trúc-thư-mục)
7. [Câu hỏi thường gặp](#7-câu-hỏi-thường-gặp)

### Bắt đầu nhanh

```bash
git clone <url-repo-này> && cd <thư-mục-repo>
# Windows: nhấp đúp run.bat   ·   macOS/Linux:
chmod +x run.sh && ./run.sh
# → mở http://localhost:8000, vào Cài đặt chọn AI, chép video nền vào nen_video/ và meme vào meme/
```

`config.json` được tạo tự động lần chạy đầu và **không được đưa lên Git** (chứa API key).

---

## 1. Cài đặt trên Windows 10/11

Không cần GPU. Cần Internet cho giọng đọc Edge-TTS và AI.

### Bước 1 — Cài Python 3.11 trở lên
Tải tại <https://www.python.org/downloads/>. Khi cài **nhớ tick "Add Python to PATH"**.

### Bước 2 — Cài FFmpeg
Cách nhanh nhất: mở **PowerShell** và chạy

```powershell
winget install Gyan.FFmpeg
```

Hoặc cài tay: tải bản *release full* tại <https://www.gyan.dev/ffmpeg/builds/>, giải nén (ví dụ vào `C:\ffmpeg`),
rồi thêm `C:\ffmpeg\bin` vào biến môi trường **Path** (Start → gõ "environment variables" → Path → New).

Đóng hết cửa sổ dòng lệnh, mở lại và kiểm tra: `ffmpeg -version`.

### Bước 3 — Chạy tool
Nhấp đúp **`run.bat`**. Lần đầu script sẽ tự:
1. tạo môi trường ảo `.venv` và cài thư viện trong `requirements.txt`;
2. cài trình duyệt Chromium cho Playwright (`playwright install chromium`) — dùng cho tính năng dán link Threads;
3. mở trình duyệt tại **<http://localhost:8000>**.

Giữ cửa sổ đen đó mở trong lúc dùng tool. Nhấn `Ctrl+C` để tắt.

### macOS / Linux

```bash
# macOS
brew install python@3.11 ffmpeg
# Ubuntu/Debian
sudo apt install python3.11 python3.11-venv ffmpeg

chmod +x run.sh && ./run.sh
# Linux: nếu tính năng dán link báo thiếu thư viện hệ thống:
sudo .venv/bin/playwright install-deps chromium
```

### Docker

```bash
docker build -t threads-video .
docker run -p 8000:8000 -v "$PWD/nen_video:/app/nen_video" -v "$PWD/meme:/app/meme" \
  -v "$PWD/nhac_nen:/app/nhac_nen" -v "$PWD/video_da_duyet:/app/video_da_duyet" \
  -v "$PWD/projects:/app/projects" threads-video
```

### Cài Playwright thủ công (nếu cần)

```bash
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install playwright
playwright install chromium
```

---

## 2. Lấy API key AI

AI dùng để đọc chữ từ ảnh, chia câu, chọn meme, lọc bình luận và gợi ý caption. Chọn **một** nhà cung cấp
(hoặc dùng Ollama chạy trên máy, không cần key — xem mục [Ollama](#️-ai-chạy-trên-máy-không-cần-api-key--ollama)):

| Nhà cung cấp | Lấy key | Ghi chú |
|---|---|---|
| **Gemini** (khuyên dùng) | <https://aistudio.google.com/app/apikey> → *Create API key* | Có hạn mức miễn phí theo ngày |
| **Claude** | <https://console.anthropic.com/settings/keys> → *Create Key* | Trả phí theo lượng dùng |
| **OpenAI** | <https://platform.openai.com/api-keys> → *Create new secret key* | Trả phí theo lượng dùng |
| **Z.ai (GLM)** | Trang *API Keys* của z.ai | Trả theo token, rất rẻ |
| **OpenRouter** | <https://openrouter.ai/keys> | Có model `:free` miễn phí (giới hạn tốc độ) |

Mở **Cài đặt** (<http://localhost:8000/settings>) → chọn nhà cung cấp → dán key → **Lưu & kiểm tra kết nối AI**.

- Key chỉ lưu trong `config.json` trên máy bạn, sau khi lưu chỉ hiển thị dạng `****abcd`. Đừng gửi file này cho ai.
- Ô **Model** để trống là dùng model mặc định (Gemini `gemini-3.8-flash`, Claude `claude-sonnet-5-5`, OpenAI `gpt-4o-mini`, Z.ai `glm-5.3-flash`, OpenRouter `z-ai/glm-5.3-flash:free`).
- **Z.ai (GLM):** tạo key ở trang API Keys của z.ai, nạp tiền ở **Billing** (trả theo token, khoảng 0,002–0,003 USD/video). KHÔNG cần mua GLM Coding Plan — gói đó chỉ dành cho công cụ lập trình.
- **OpenRouter:** tạo key ở openrouter.ai/keys. Model có đuôi `:free` (vd `z-ai/glm-5.3-flash:free`) miễn phí nhưng bị giới hạn tốc độ; gặp lỗi 429 tool tự đợi 20 giây và thử lại 3 lần.
- **OpenAI Base URL:** để trống = OpenAI. Điền URL khác để dùng bất kỳ dịch vụ nào tương thích OpenAI.
- **Dự phòng:** chọn nhà cung cấp thứ 2 (đã nhập key). Khi nhà cung cấp chính hết tiền / hết hạn mức / bị giới hạn tốc độ, tool tự chuyển sang dự phòng. Ví dụ: chính = Gemini (miễn phí), dự phòng = Z.ai.
  Có thể nhập model khác, ví dụ model rẻ hơn của cùng nhà cung cấp.
- Với Claude, tool bật chế độ *fallback* phía máy chủ: nếu model chính từ chối nội dung vì bộ lọc an toàn,
  Anthropic tự chạy lại yêu cầu trên model dự phòng (tính phí theo model dự phòng).
- **Chưa có key vẫn dùng được**: bạn tự gõ chữ cho từng thẻ; tool chia câu bằng quy tắc và chọn meme ngẫu nhiên.

---

## 3. Các thư mục: video nền, meme, video đã duyệt

| Thư mục (mặc định, nằm trong thư mục tool) | Nội dung |
|---|---|
| `nen_video/` | Video gameplay làm nền (MP4/MOV/MKV/WebM). Tool tự cắt về 9:16, làm tối nhẹ, tắt tiếng, bắt đầu ở đoạn ngẫu nhiên, lặp lại nếu ngắn. |
| `meme/` | Meme dạng ảnh (PNG nên nền trong suốt, JPG, WebP), GIF động, hoặc **video ngắn** (MP4/WebM/MOV). Meme video phát kèm tiếng của nó. |
| `nhac_nen/` | Nhạc nền (MP3, WAV, M4A, OGG, FLAC) — xem mục [Nhạc nền](#-nhạc-nền). |
| `video_da_duyet/` | Video bạn bấm **✅ Duyệt & lưu** sau khi render, kèm file `.txt` cùng tên chứa tiêu đề + caption + hashtag. |

- Cứ **chép file thẳng vào thư mục** bằng Explorer là được (rồi bấm "↻ Làm mới" trên web), hoặc kéo thả trên trang **Thư viện**.
  Video nền nặng vài GB nên chép thẳng vào thư mục.
- Muốn dùng thư mục ở chỗ khác (ví dụ `D:\Video\Gameplay`): **Cài đặt → 📁 Thư mục**, nhập đường dẫn đầy đủ.
- Khi tạo video: mục **🎮 Video nền** ở bước 1 và bước Duyệt — chọn 🎲 *Ngẫu nhiên* (không trùng 3 lần gần nhất) hoặc một video cụ thể.
  Meme do AI chọn từ thư mục `meme/`; ở bước Duyệt bạn bấm vào ô meme của từng câu để đổi (có ảnh xem trước, video có dấu ▶).

Ngoài ra: tiếng "bụp" khi meme hiện ở `library/sfx/pop.mp3` (thay được).

**Trang Thư viện** (<http://localhost:8000/memes>) có các tab tương ứng từng thư mục, mỗi tab có nút **📂 Mở thư mục**:
- Kéo thả meme ảnh/GIF/video, video nền.
- **🤖 AI gắn nhãn**: AI xem ảnh và điền tên, mô tả, nhãn cảm xúc (`khinh bỉ, mỉa mai, cạn lời…`). Có nút gắn nhãn hàng loạt cho meme chưa có nhãn.
- **✨ Xóa nền trắng** (meme ảnh tĩnh): biến nền trắng quanh meme thành trong suốt (loang màu từ 4 góc, không xóa phần trắng bên trong như mắt, răng).
- Tab **Video đã duyệt**: xem lại, tải về, mở file caption.
- AI chọn meme dựa vào tên + nhãn + mô tả — nhãn càng rõ cảm xúc, meme càng đúng chỗ.

---

## 4. Làm video

### Cách 1 — Upload ảnh chụp
1. Trang chủ → **Upload ảnh chụp** → kéo thả ảnh → **Cắt thẻ từ ảnh**.
   Một ảnh có nhiều thẻ sẽ được tách riêng từng thẻ; thanh trạng thái điện thoại, viền đen, nền game bị bỏ.
2. AI đọc chữ từng thẻ, tự che tên/avatar **người bình luận** (tác giả bài gốc có công tắc riêng trong Cài đặt)
   và sắp xếp theo số thứ tự "1/7, 2/7…" nếu có.
3. Ở bước **Thẻ**: kéo ⠿ để đổi thứ tự, sửa chữ nếu AI đọc sai, đổi loại *Bài gốc / Bình luận*,
   **✂ Cắt lại** nếu cắt sai, hoặc bấm vào ảnh gốc để kéo khung cắt thêm thẻ.

### Cách 2 — Dán link Threads
Dán link dạng `https://www.threads.com/@ten/post/...` (hỗ trợ cả `threads.net`) → **Lấy bài và bình luận**.
Tool lấy cả chuỗi bài 1/N của cùng tác giả, lọc rác (chỉ @tag, chỉ emoji, có link, dưới 5 hoặc trên 80 chữ, trùng nhau),
AI chọn 3–6 bình luận hay và đa dạng, rồi tự vẽ thẻ kiểu Threads; người bình luận hiện là "Người dùng 1, 2…".
Không đăng nhập thì thường lấy được khoảng 20 bình luận đầu. Có thể nhập cookie (có rủi ro, xem cảnh báo trong tool).
Nếu Threads chặn, tool báo lỗi và gợi ý dùng cách upload ảnh.

### Duyệt và render
- **Lên kế hoạch** → bảng duyệt: mỗi câu có *chữ hiển thị*, *chữ để đọc* (số và viết tắt đã viết ra chữ, sửa được),
  meme (bấm để chọn từ danh sách có ảnh nhỏ, hoặc "Không"), nút ▶ **nghe thử**.
- **Render video** → xem tiến độ → xem trước, tải MP4, copy tiêu đề / caption / hashtag.
- Ưng ý thì bấm **✅ Duyệt & lưu** → video được chép vào `video_da_duyet/` (tên file có ngày giờ + tiêu đề) kèm file `.txt` caption.
- **Sửa kế hoạch & render lại**: giọng đọc được cache theo (câu + giọng + tốc độ), nên chỉ những câu bị sửa mới phải tạo lại.
- Công tắc **Tự động hoàn toàn** (góc trên): bỏ qua bước duyệt, bấm một nút ở bước 1 là ra video.

### Luật meme (tự áp dụng, kể cả khi AI quên)
Câu đầu tiên của video không có meme · không 2 câu liền nhau đều có meme · mỗi meme tối đa 2 lần/video ·
mật độ *Ít* (~1 meme/thẻ), *Vừa* (~1 meme mỗi 2–3 câu), *Nhiều* (~1 meme mỗi 1–2 câu).
Meme hiện đúng đầu câu được gán, kéo dài `max(1,5; min(2,5; độ dài câu))` giây.

---

## 5. Kiểm tra nhanh (self-test)

```bash
python -m app.selftest            # dùng AI nếu đã có key, Edge-TTS nếu có mạng
python -m app.selftest --offline  # không gọi AI/Edge-TTS (giọng đọc thay bằng tiếng bíp)
```

Chạy toàn bộ pipeline thật (cắt thẻ → đọc chữ → lên kế hoạch → giọng đọc → timeline → render) với dữ liệu mẫu trong
`samples/`: 2 ảnh chụp (ảnh 1 chứa 2 thẻ), 3 meme (có 1 GIF động), 1 video nền tự sinh bằng FFmpeg `testsrc2`, 1 đoạn nhạc.
Kết quả: `samples/out.mp4`, kèm kiểm tra cắt đúng 2 thẻ, luật meme, độ dài/độ phân giải/codec, thẻ khớp giọng đọc.
Self-test chạy trong `samples/_work/`, không đụng vào thư viện thật của bạn.

---

## 6. Cấu trúc thư mục

```
app/
  main.py              FastAPI: trang web + API, job render chạy nền, tiến độ qua SSE
  config.py            đọc/ghi config.json
  assets.py            tạo thư mục, tải font, tạo âm "bụp" lần đầu
  selftest.py          python -m app.selftest
  llm/                 base.py (retry + gửi lại khi JSON sai schema), gemini.py, claude.py, openai_llm.py,
                       ollama.py (AI trên máy), factory.py (chọn nhà cung cấp + dự phòng)
  pipeline/
    crop.py            cắt thẻ từ ảnh chụp, cắt tay, che vùng tên
    ocr.py             AI đọc chữ (prompt B1)
    threads_fetch.py   lấy bài + bình luận từ link (Playwright)
    comment_filter.py  lọc rác + AI chọn bình luận (prompt B3), ẩn danh
    planner.py         AI chia câu + chọn meme (prompt B2), kiểm tra lại luật meme
    textnorm.py        chuẩn hóa chữ để đọc (số → chữ, viết tắt, bỏ * / emoji / "1/7")
    card_render.py     tự vẽ thẻ kiểu Threads
    tts/               base.py, edge.py, vieneu.py (cùng interface) + cache
    timeline.py        mốc thời gian, bố cục thẻ/meme, chia Part
    render.py          dựng lệnh FFmpeg (filter_complex)
    memes.py           thư viện meme, AI gắn nhãn (B4), xóa nền trắng
    media.py           3 thư mục: liệt kê, ảnh xem trước, mở thư mục
    caption.py         gợi ý caption (B5)
    project.py         điều phối một dự án
  prompts/             ocr.md (B1), planner.md (B2), comment_filter.md (B3), meme_tagger.md (B4), caption.md (B5)
  fonts/               Be Vietnam Pro (giấy phép OFL)
  static/              index.html, memes.html, settings.html, css/, js/
nen_video/             video nền gameplay (đổi được trong Cài đặt)
meme/                  meme ảnh / GIF / video (đổi được trong Cài đặt)
nhac_nen/              nhạc nền (đổi được trong Cài đặt)
video_da_duyet/        video đã duyệt + file .txt caption (đổi được trong Cài đặt)
library/               memes.json (nhãn meme) · sfx/pop.mp3 · lịch sử chọn nhạc/nền
projects/<id>/         input/, cards/, plan.json, timeline.json, output_*.mp4 của từng video
cache/tts/             giọng đọc đã tạo (xóa thoải mái, sẽ tạo lại)
samples/               dữ liệu cho self-test
config.json            cấu hình (có API key — không chia sẻ)
```

Các prompt AI nằm trong `app/prompts/*.md` và được nạp lúc chạy — sửa file là có hiệu lực ngay, không cần sửa code.

---

## 7. Câu hỏi thường gặp

**Báo "Không tìm thấy ffmpeg"** — Cài FFmpeg (mục 1) rồi **mở lại** cửa sổ dòng lệnh để nhận PATH mới.

**"API key … không hợp lệ" / "hết quota"** — Kiểm tra key trong Cài đặt. Gemini miễn phí có giới hạn theo phút/ngày: đợi rồi thử lại.

**Giọng đọc lỗi "Edge-TTS không tạo được giọng đọc"** — Edge-TTS cần Internet và máy chủ Microsoft thỉnh thoảng từ chối
một câu trong một lúc (nhất là khi gọi dồn dập); tool đã tự thử lại 7 lần có giãn cách. Nếu vẫn lỗi, đợi một lát rồi bấm
**↻ Thử lại** — các câu đã tạo xong được giữ trong cache.

**Không lấy được bài từ link** — Threads thay đổi giao diện và chặn truy cập tự động thường xuyên. Thử lại sau, dùng cookie
(Cài đặt → Threads), hoặc chụp màn hình rồi dùng cách upload ảnh. Báo "thiếu Chromium" thì chạy `playwright install chromium`.

**Cắt thẻ sai** — Bấm **✂ Cắt lại** ở thẻ đó và kéo khung, hoặc bấm vào ảnh gốc để cắt thêm thẻ. Thuật toán tìm vùng nền
trắng/sáng lớn, nên ảnh chụp chế độ tối (dark mode) thường cần cắt tay.

**VieNeu-TTS (offline)** — Không cài sẵn vì nặng. Thử `pip install vieneu` trong `.venv` rồi chọn trong Cài đặt.
Tích hợp này là thử nghiệm: nếu phiên bản thư viện có cách gọi khác, tool sẽ báo lỗi rõ ràng — khi đó dùng Edge-TTS.

**Render bao lâu?** — Phần dựng hình trên CPU phổ thông nhanh hơn thời gian thực (video 60 giây ≈ 30–60 giây).
Lần đầu cộng thêm thời gian tạo giọng đọc qua mạng.

---

Font Be Vietnam Pro © The Be Vietnam Pro Project Authors — SIL Open Font License 1.1 (`app/fonts/OFL.txt`).


## 🎵 Nhạc nền

- Chép file nhạc (MP3, WAV, M4A, OGG, FLAC) vào thư mục **`nhac_nen`** (đổi được trong Cài đặt → Thư mục), hoặc tải lên ở **Thư viện → 🎵 Nhạc nền**.
- Khi tạo video, chọn nhạc ở bước 1 hoặc bước Duyệt: **🎲 Ngẫu nhiên** (tránh lặp 2 bài gần nhất), **🔇 Không nhạc**, hoặc một bài cụ thể (bấm ▶ để nghe thử).
- Nhạc chạy nhỏ dưới giọng đọc (âm lượng chỉnh trong Cài đặt), tự lặp nếu ngắn hơn video, nhỏ dần ở giây cuối. Video chia nhiều Part dùng chung một bài.
- Repo không kèm sẵn nhạc. Nên dùng nhạc không bản quyền từ YouTube Audio Library hoặc Pixabay Music để tránh bị gỡ video.


## 🖥️ AI chạy trên máy (không cần API key) — Ollama

Phù hợp máy có card NVIDIA 6 GB như **GTX 1660 Ti** + RAM 16 GB.

1. Tải và cài **Ollama**: https://ollama.com/download → mở ứng dụng (biểu tượng con lạc đà ở khay hệ thống).
2. Trong tool: **Cài đặt → AI → 🖥️ Máy này (Ollama)**. Tool tự kiểm tra Ollama.
3. Bấm **⬇ Tải** ở dòng `qwen3.5:4b` (~3,4 GB, tải 1 lần) — model này vừa **đọc chữ trong ảnh** vừa **chia câu, chọn meme, lọc bình luận, viết caption**.
4. Bấm **Lưu & kiểm tra kết nối AI** → thấy "Chạy 100% trên card đồ họa ✅" là xong.

Mẹo:
- Lần gọi đầu mất 10–30 giây để nạp model vào card; các lần sau nhanh (model giữ trong card 15 phút).
- Báo "đang chạy bằng CPU" → cập nhật driver NVIDIA rồi khởi động lại Ollama.
- Có thể đặt **Dự phòng = Máy này (Ollama)** khi dùng Gemini: hết hạn mức Gemini thì tự chuyển sang AI trên máy.
- Ollama tắt / chưa cài: chia câu và chọn meme vẫn chạy bằng **chế độ không AI** (chọn meme theo từ khóa cảm xúc); riêng bước đọc chữ từ ảnh cần AI (hoặc tự gõ chữ vào thẻ).
