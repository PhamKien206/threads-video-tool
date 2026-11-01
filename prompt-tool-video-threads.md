# PROMPT: Xây tool web tự dựng video "Threads + gameplay + meme + giọng đọc"

> **Cách dùng:** copy toàn bộ **Phần A** gửi cho AI lập trình (Claude Code, Cursor, Codex…) để nó viết tool. **Phần B** là các prompt chạy bên trong tool, AI lập trình sẽ đưa nguyên văn vào code.
> Những chỗ có `【MẶC ĐỊNH】` là giá trị mình tự chọn vì bạn chưa chốt. Sửa trực tiếp trước khi gửi.

---

# PHẦN A: PROMPT GIAO VIỆC CHO AI LẬP TRÌNH

## Vai trò
Bạn là kỹ sư full-stack, thạo Python, FFmpeg và xử lý ảnh. Hãy xây một **web app chạy local** để tự động dựng video dọc 9:16 theo phong cách "đọc bài Threads trên nền gameplay, có meme phản ứng". Viết code hoàn chỉnh, chạy được ngay, có README tiếng Việt.

## Kết quả mong muốn
Người dùng upload ảnh chụp bài Threads **hoặc** dán link Threads, rồi bấm nút. Tool cho ra file MP4 với:
- Nền là video gameplay (Minecraft parkour…), chạy suốt video, tắt tiếng, làm tối nhẹ.
- Thẻ bài Threads hiện lần lượt ở nửa trên màn hình. Thẻ mới xuất hiện bên dưới thẻ cũ, tối đa 2 thẻ cùng lúc, thẻ thứ 3 vào thì thẻ đầu trượt lên và biến mất.
- Giọng đọc tiếng Việt đọc **chỉ phần thân bài**. Mỗi thẻ ở trên màn hình đúng bằng thời gian đọc của nó.
- Meme lấy từ thư viện của người dùng. AI chọn meme theo cảm xúc từng câu. Meme bật lên ở khoảng trống dưới thẻ, đúng lúc bắt đầu câu được gán, có hiệu ứng nảy và âm "bụp".
- Nhạc nền nhỏ phía dưới giọng đọc.

## Cấu hình đã chốt
| Mục | Giá trị |
|---|---|
| Hệ điều hành | `【MẶC ĐỊNH】` Windows 10/11, không cần GPU (vẫn phải chạy được trên Mac/Linux) |
| Giọng đọc mặc định | `【MẶC ĐỊNH】` Edge-TTS `vi-VN-HoaiMyNeural`, tốc độ +15%. Có thêm lựa chọn **VieNeu-TTS** (offline) |
| AI (đọc ảnh + lên kế hoạch) | `【MẶC ĐỊNH】` Hỗ trợ cả 3: Gemini, Claude, OpenAI. Người dùng nhập key trong trang Cài đặt và chọn nhà cung cấp |
| Bước duyệt kế hoạch | Có, kèm công tắc "Tự động hoàn toàn" để bỏ qua |
| Đọc tên tài khoản | **Không** |
| Phụ đề riêng | **Không** (chữ đã có trên thẻ) |
| Nhạc nền / âm "bụp" | Bật, nhạc ở 12% âm lượng |
| Độ dài tối đa | `【MẶC ĐỊNH】` 90 giây. Dài hơn thì tự chia Part 1, Part 2… và chèn chữ "Part N" ở góc |
| Mật độ meme | Vừa: khoảng 1 meme mỗi 2–3 câu, không 2 câu liền nhau đều có meme, mỗi meme dùng tối đa 2 lần mỗi video |
| Watermark | `【MẶC ĐỊNH】` Tắt, có ô nhập tên kênh trong Cài đặt |
| Che tên trên thẻ | Che người bình luận. Tác giả bài gốc: `【MẶC ĐỊNH】` không che, có công tắc |
| Nguồn link | Chỉ Threads (bản đầu) |
| Số bình luận | 3–6, có câu chuyển "Và đây là bình luận của cư dân mạng:" (có thể tắt) |
| Xuất video | MP4 1080×1920, 30fps, H.264 (`-preset veryfast -crf 20`) + AAC |

## Công nghệ bắt buộc
- Backend: **Python 3.11 + FastAPI**. Việc render nặng chạy ở background task, giao diện xem tiến độ qua SSE hoặc polling.
- Frontend: **HTML + JS thuần** (có thể dùng Alpine.js hoặc htmx), phục vụ tĩnh từ FastAPI tại `http://localhost:8000`.
- Ảnh: OpenCV, Pillow. Render: **FFmpeg** (gọi qua subprocess, dựng filter_complex). Không dùng MoviePy cho bước render cuối vì chậm.
- Lấy dữ liệu từ link Threads: **Playwright (Chromium headless)**, chặn bắt các response GraphQL/JSON của trang để lấy bài và bình luận, chỉ đọc DOM khi không bắt được.
- Lưu trữ: file JSON và thư mục, không cần database.
- Phải có `requirements.txt`, `run.bat`, `run.sh` và `Dockerfile`.

## Cấu trúc thư mục
```
app/
  main.py              # FastAPI routes
  pipeline/
    crop.py            # cắt thẻ từ ảnh chụp
    ocr.py             # AI đọc chữ (prompt B1)
    threads_fetch.py   # lấy bài + bình luận từ link
    comment_filter.py  # lọc rác + AI chấm bình luận (prompt B3)
    planner.py         # AI chia câu + chọn meme (prompt B2)
    card_render.py     # tự vẽ thẻ kiểu Threads từ chữ
    tts/               # base.py, edge.py, vieneu.py (cùng interface)
    timeline.py        # tính mốc thời gian
    render.py          # dựng lệnh FFmpeg
  llm/                 # base.py, gemini.py, claude.py, openai.py (cùng interface)
  prompts/             # B1–B4 dạng file .md, nạp lúc chạy
  static/              # giao diện
library/
  memes/  memes.json
  backgrounds/
  music/  sfx/pop.mp3
projects/<id>/         # mỗi lần làm video: input, cards, audio, plan.json, output.mp4
config.json
```

## Luồng xử lý chi tiết

### Nguồn 1: ảnh upload
1. **Cắt thẻ** (`crop.py`): tìm các vùng chữ nhật nền trắng hoặc sáng lớn (threshold, morphology, findContours, lọc theo diện tích lớn hơn 15% ảnh và tỉ lệ khung hợp lý). Một ảnh có thể chứa **nhiều thẻ** thì tách riêng từng thẻ, sắp từ trên xuống dưới. Bỏ thanh trạng thái điện thoại và viền đen. Giao diện có nút cắt tay (kéo khung) khi cắt sai.
2. **AI đọc chữ** (`ocr.py`): gửi từng ảnh thẻ cho LLM có khả năng đọc ảnh, dùng **prompt B1**. Nhận JSON gồm thân bài sạch, số thứ tự (vd 1/7) và vị trí vùng tên/avatar (để che nếu cần).
3. Sắp xếp các thẻ theo số thứ tự. Nếu không có số thì theo thứ tự upload. Người dùng kéo thả để đổi thứ tự.

### Nguồn 2: link Threads
1. **Lấy dữ liệu** (`threads_fetch.py`): mở link bằng Playwright, chờ trang tải, cuộn để tải thêm bình luận. Lấy bài gốc (cả chuỗi 1/N nếu cùng tác giả đăng nối tiếp), bình luận (text, like, số trả lời, username, thời gian). Hỗ trợ cả domain `threads.net` và `threads.com`.
   - Không đăng nhập thì chấp nhận khoảng 20 bình luận. Có ô tùy chọn nhập cookie (cảnh báo rủi ro).
   - Lỗi hoặc bị chặn thì báo lỗi rõ bằng tiếng Việt và gợi ý dùng cách upload ảnh.
2. **Lọc bình luận** (`comment_filter.py`):
   - Lọc thô bằng code: bỏ bình luận chỉ có @tag, chỉ có emoji, có link, dưới 5 chữ, trên 80 chữ, hoặc trùng nhau.
   - Lọc tinh bằng AI (**prompt B3**): chọn 3–6 bình luận hay và đa dạng góc nhìn.
3. **Vẽ thẻ** (`card_render.py`): tự vẽ thẻ kiểu Threads bằng Pillow. Nền trắng, bo góc 0, padding 28px, font **Be Vietnam Pro** (đi kèm trong repo) cỡ 34px. Header có avatar tròn, tên, "· thời gian" màu xám. Thẻ bình luận có đường kẻ dọc màu xám bên trái. Người bình luận hiển thị là "Người dùng 1, 2…" và avatar xám trơn.

### Bước chung (sau khi có danh sách thẻ + chữ)
4. **Lên kế hoạch** (`planner.py`): gửi toàn bộ chữ và danh sách meme (`memes.json`) cho LLM bằng **prompt B2**. Nhận `plan.json` (schema bên dưới). Kiểm tra lại bằng code: meme phải tồn tại, áp luật mật độ meme. Sai thì sửa tự động.
5. **Màn hình duyệt** (bỏ qua nếu bật "Tự động hoàn toàn"): bảng gồm thẻ, các câu, chữ để đọc (sửa được) và meme (dropdown có ảnh nhỏ, có thể chọn "không"). Có nút "Nghe thử câu này" và nút **Render**.
6. **TTS** (`tts/`): tạo **1 file audio cho mỗi câu**, đo thời lượng bằng ffprobe. Nghỉ 0,3 giây giữa các câu và 0,5 giây giữa các thẻ. Cache theo hash(text + voice + speed).
7. **Timeline** (`timeline.py`): tính mốc bắt đầu và kết thúc cho từng câu, từng thẻ, từng meme. Meme xuất hiện ở đầu câu được gán, kéo dài `max(1.5, min(2.5, độ dài câu))` giây.
8. **Render** (`render.py`): một lệnh FFmpeg duy nhất:
   - Nền: chọn ngẫu nhiên file trong `library/backgrounds/` và điểm bắt đầu ngẫu nhiên, tránh trùng 3 lần render gần nhất. Scale và crop về 1080×1920, `eq=brightness=-0.08`. Nếu nền ngắn hơn video thì lặp lại.
   - Thẻ: scale rộng 920px, đặt cách mép trên 260px. Thẻ thứ hai đặt dưới thẻ thứ nhất, cách 24px. Hiệu ứng vào là fade cộng trượt lên 40px trong 0,25 giây. Khi đẩy thẻ cũ thì trượt lên và fade out.
   - Meme: cao khoảng 420px, đặt giữa theo chiều ngang, ngay dưới thẻ cuối, cách 40px (không được tràn khỏi khung, thiếu chỗ thì đặt ở 1/3 dưới màn hình). Hiệu ứng nảy dùng scale theo biểu thức thời gian: 0 → 1,1 → 1,0 trong 0,3 giây. Hỗ trợ PNG trong suốt và GIF (`-ignore_loop 0`).
   - Audio: giọng đọc + nhạc nền (12%, fade out 1 giây cuối) + `sfx/pop.mp3` tại mỗi lần meme xuất hiện (40%). Chuẩn hóa loudness `loudnorm` khoảng −14 LUFS.
   - Hiển thị tiến độ render (phân tích `-progress pipe:1`).
9. **Kết quả**: xem trước video trên web, tải xuống, kèm gợi ý tiêu đề, caption và hashtag (**prompt B5**).

## Schema `plan.json`
```json
{
  "cards": [
    {
      "card_id": "c1",
      "image": "cards/c1.png",
      "kind": "post | comment",
      "sentences": [
        {
          "id": "c1s1",
          "display_text": "Ở đời có một chân lý chua hơn bát canh dưa khú:",
          "speak_text": "Ở đời có một chân lý chua hơn bát canh dưa khú.",
          "emotion": "mỉa mai",
          "meme": null,
          "meme_reason": null
        }
      ]
    }
  ],
  "transition_before_comments": "Và đây là bình luận của cư dân mạng:",
  "title_suggestion": "...",
  "hashtags": ["#threads", "#giadinh"]
}
```

## Thư viện meme (trang quản lý)
- Upload PNG, GIF, WebP. Mỗi meme có `file`, `name`, `tags` (danh sách cảm xúc hoặc ngữ cảnh), `description`.
- Nút **"AI gắn nhãn"** cho meme chưa có nhãn, dùng **prompt B4**.
- Nút tùy chọn **"Xóa nền trắng"**: flood fill từ các góc rồi chuyển vùng đó thành trong suốt.
- `memes.json` ví dụ:
```json
[{"file": "meo_khinh_bi.png", "name": "Mèo khinh bỉ", "tags": ["khinh bỉ","mỉa mai","ờ hớ","coi thường"], "description": "Mèo nheo mắt, nhếch mép nhìn khinh khỉnh"}]
```

## Trang Cài đặt
API key và nhà cung cấp LLM, giọng TTS (chọn giọng, tốc độ, nút nghe thử), âm lượng nhạc và SFX, độ dài tối đa, mật độ meme, các công tắc (che tên tác giả, câu chuyển cảnh, tự động hoàn toàn), tên kênh/watermark, cookie Threads (tùy chọn). Lưu vào `config.json`. Key không bao giờ gửi xuống frontend sau khi lưu (chỉ hiển thị dạng `****abcd`).

## Yêu cầu chất lượng
- Mọi thông báo lỗi trên giao diện bằng tiếng Việt, dễ hiểu.
- Gọi LLM có retry 2 lần. Nếu JSON trả về sai schema thì gửi lại kèm thông báo lỗi.
- Có thư mục `samples/` và lệnh `python -m app.selftest` chạy toàn bộ pipeline với 2 ảnh mẫu, 3 meme mẫu, 1 nền mẫu (nền mẫu tự sinh bằng FFmpeg `testsrc` nếu không có), xuất ra `samples/out.mp4`.
- README tiếng Việt: cài FFmpeg trên Windows, cài Playwright (`playwright install chromium`), lấy API key, chạy tool, thêm meme và nền.

## Tiêu chí nghiệm thu
- [ ] Ảnh có 2 thẻ trong 1 ảnh thì cắt đúng thành 2 thẻ.
- [ ] Giọng đọc không đọc tên, thời gian, nhãn, "1/7", dấu `*`. Bắt đầu đọc ngay từ câu đầu thân bài.
- [ ] Thẻ hiện và ẩn khớp giọng đọc (lệch dưới 0,1 giây).
- [ ] Meme đúng câu, hợp cảm xúc, tuân luật mật độ.
- [ ] Link Threads công khai thì lấy được bài và bình luận, lọc ra 3–6 bình luận hay, tên người bình luận đã được che.
- [ ] Video 60 giây render dưới 2 phút trên laptop CPU phổ thông.
- [ ] Sửa chữ hoặc đổi meme ở màn hình duyệt rồi render lại được, không phải làm lại từ đầu (dùng cache).

Hãy bắt đầu bằng việc tóm tắt kế hoạch triển khai trong 10 dòng, rồi viết code theo thứ tự: crop → ocr → planner → tts → timeline → render → giao diện → threads_fetch → comment_filter → trang meme/cài đặt → selftest → README.

---

# PHẦN B: CÁC PROMPT CHẠY BÊN TRONG TOOL

> Lưu mỗi prompt thành file trong `app/prompts/`. Biến trong `{{ }}` được code điền vào. Tất cả đều yêu cầu **chỉ trả về JSON**.

## B1. Đọc chữ từ ảnh thẻ Threads (`ocr.md`)
```
Bạn nhận một ảnh chụp MỘT thẻ bài viết hoặc bình luận trên mạng xã hội Threads, nội dung tiếng Việt.
Nhiệm vụ: chép lại CHÍNH XÁC phần thân bài, giữ nguyên dấu tiếng Việt, xuống dòng và chính tả gốc.

BỎ, không chép:
- Tên tài khoản, tên nhóm/cộng đồng, dấu ">" giữa chúng
- Thời gian đăng ("6 giờ", "2 ngày"...), nhãn ("Thành viên cộng đồng", "Tác giả"...)
- Logo/chữ "threads", số thứ tự dạng "1/7", "2/7"
- Số like/bình luận/chia sẻ, nút "Trả lời", "Xem thêm", "Dịch"
- Bất kỳ chữ nào nằm NGOÀI khung thẻ (thanh trạng thái điện thoại, nền game phía sau)

Trả về JSON:
{
  "body": "<thân bài, giữ xuống dòng bằng \n>",
  "part_index": <số thứ tự nếu thấy "x/y" thì x, không thì null>,
  "part_total": <y hoặc null>,
  "author_box": [x1, y1, x2, y2] hoặc null,   // vùng chứa avatar + tên + thời gian, theo pixel
  "is_reply": true/false,                       // có đường kẻ trả lời bên trái hoặc là bình luận
  "uncertain_words": ["các từ bạn không chắc đã đọc đúng"]
}
Không bịa thêm chữ. Chữ bị cắt mất ở mép ảnh thì ghi "..." tại chỗ đó.
```

## B2. Chia câu, chuẩn hóa giọng đọc và chọn meme (`planner.md`)
```
Bạn là biên tập viên video TikTok tiếng Việt, chuyên dạng "đọc bài Threads có meme phản ứng".

ĐẦU VÀO
- Danh sách thẻ theo thứ tự (mỗi thẻ: card_id, kind = post|comment, body):
{{CARDS_JSON}}
- Thư viện meme (file, name, tags, description):
{{MEMES_JSON}}
- Mật độ meme: {{MEME_DENSITY}}   // "ít" | "vừa" | "nhiều"

NHIỆM VỤ
1. Tách mỗi thẻ thành các câu đọc tự nhiên (mỗi câu 6–30 từ; câu quá dài thì tách ở dấu phẩy hợp lý).
2. Với mỗi câu tạo:
   - display_text: nguyên văn như trên thẻ.
   - speak_text: bản để máy đọc:
     • bỏ ký tự đầu dòng (*, •, -), bỏ emoji, bỏ dấu ngoặc kép và ngoặc đơn nhưng giữ nội dung
       (vd "(Người hùng cứu thế)" → ", người hùng cứu thế,")
     • số và ký hiệu đọc thành chữ: "90%" → "chín mươi phần trăm", "15 phút" → "mười lăm phút",
       "3 bữa" → "ba bữa", "triệu bạc" giữ nguyên
     • viết tắt phổ biến đọc đầy đủ: "ko/k" → "không", "dc/đc" → "được", "ng" → "người", "vs" → "với"
     • KHÔNG thay đổi ý, KHÔNG thêm lời bình
   - emotion: 1–3 từ mô tả cảm xúc/giọng điệu của câu (mỉa mai, cay đắng, bất ngờ, tủi thân, hài hước, bức xúc, trung tính...)
3. Chọn meme:
   - Chỉ chọn file có trong thư viện. Meme phải KHỚP CẢM XÚC hoặc là PHẢN ỨNG hợp lý của người xem với câu đó.
   - Ưu tiên câu "đắt": câu chốt, câu châm biếm, chi tiết gây sốc, câu đảo ngược.
   - Mật độ "ít": khoảng 1 meme/thẻ; "vừa": 1 meme mỗi 2–3 câu; "nhiều": 1 meme mỗi 1–2 câu.
   - Không gán meme cho 2 câu liền nhau. Mỗi meme tối đa 2 lần cả video. Câu đầu tiên của video KHÔNG gán meme.
   - Không có meme nào hợp thì để null, đừng ép.
   - meme_reason: 1 câu ngắn giải thích.
4. Gợi ý title_suggestion (dưới 60 ký tự, gây tò mò, không giật tít sai sự thật) và 3–6 hashtags tiếng Việt không dấu.

Trả về DUY NHẤT JSON đúng schema:
{"cards":[{"card_id":"","sentences":[{"id":"","display_text":"","speak_text":"","emotion":"","meme":null,"meme_reason":null}]}],
 "title_suggestion":"","hashtags":[]}
```

## B3. Lọc bình luận hay (`comment_filter.md`)
```
Bạn chọn bình luận để đưa vào video TikTok tiếng Việt về bài viết sau.

BÀI GỐC:
{{POST_TEXT}}

BÌNH LUẬN ỨNG VIÊN (đã lọc rác sơ bộ; id, text, likes, replies):
{{COMMENTS_JSON}}

Chọn từ {{MIN}} đến {{MAX}} bình luận theo tiêu chí, ưu tiên từ trên xuống:
1. Có "chất": hài hước, câu chốt đắt giá, trải nghiệm cá nhân thật, phản biện sắc sảo, đồng cảm sâu.
2. Liên quan trực tiếp tới nội dung bài gốc.
3. Nhiều like thì được cộng điểm, nhưng KHÔNG chọn chỉ vì like.
4. ĐA DẠNG: có cả đồng tình và phản đối/góc nhìn khác nếu có; không chọn 2 bình luận cùng ý.
5. Tự đứng được: người xem hiểu mà không cần đọc bình luận khác.

LOẠI BỎ: công kích cá nhân, lời lẽ thô tục nặng, thông tin cá nhân (số điện thoại, địa chỉ, tên thật người khác),
quảng cáo, nội dung nhạy cảm (chính trị, tôn giáo gây chia rẽ, bạo lực, tự hại).

Sắp xếp thứ tự trình chiếu sao cho có nhịp: mở bằng bình luận đồng cảm hoặc hài, giữa là tranh luận, kết bằng câu "chốt" hay nhất.

Trả về DUY NHẤT JSON:
{"selected":[{"id":"","reason":"","stance":"đồng tình|phản đối|trung lập|hài hước"}],
 "order":["id theo thứ tự trình chiếu"]}
```

## B4. AI gắn nhãn meme (`meme_tagger.md`)
```
Đây là một ảnh meme/sticker dùng để chèn phản ứng trong video TikTok tiếng Việt.
Mô tả và gắn nhãn để AI khác có thể chọn đúng meme theo cảm xúc câu chuyện.

Trả về DUY NHẤT JSON:
{
  "name": "<tên ngắn tiếng Việt, vd 'Mèo khinh bỉ'>",
  "description": "<1 câu mô tả biểu cảm/hành động>",
  "tags": ["5–8 nhãn cảm xúc hoặc tình huống dùng, tiếng Việt, chữ thường",
           "vd: khinh bỉ, mỉa mai, ờ hớ, coi thường, cạn lời"],
  "has_text": true/false,
  "background": "trong suốt|trắng|ảnh nền"
}
```

## B5. Gợi ý caption đăng bài (`caption.md`)
```
Viết caption đăng TikTok/Reels cho video đọc bài Threads sau:
{{FULL_TEXT}}
Yêu cầu: 1–2 câu tiếng Việt tự nhiên, khơi gợi bình luận (đặt câu hỏi cho người xem), không giật tít sai sự thật,
kèm 4–6 hashtag. Trả về JSON: {"caption":"", "hashtags":[]}
```
