# Phương án: chạy tool KHÔNG cần API (AI chạy trên máy)

> Tài liệu nghiên cứu, viết ngày 31/10/2026, để duyệt trước khi code.
> Mục tiêu: không có API key (hoặc mất mạng, hết hạn mức) thì tool vẫn làm ra video, dùng AI chạy ngay trên máy bạn.
> Mục **9. Câu hỏi cần bạn trả lời** quyết định chọn model nào.

---

## 0. Tóm tắt khuyến nghị

| Việc | Cách làm khi không có API | Cần gì |
|---|---|---|
| Đọc chữ từ ảnh thẻ Threads | **PaddleOCR** (OCR chuyên dụng, hỗ trợ tiếng Việt, rất nhẹ), có thể thêm AI local để sửa lỗi dấu | CPU là đủ |
| Chia câu, chọn meme, lọc bình luận, caption, chủ đề | **Ollama** + model chữ nhỏ (**Qwen3 4B/8B** hoặc **Gemma 3/4**) qua cổng `localhost:11434` | Tốt nhất có card NVIDIA ≥ 6 GB; không có vẫn chạy được nhưng chậm |
| Máy yếu, không cài nổi AI | **Chế độ "Không AI"**: chạy bằng luật (tách câu bằng code, chọn meme theo từ khóa, lọc bình luận theo lượt thích) | Không cần gì thêm |
| Giọng đọc | **VieNeu-TTS** (đã có trong tool) chạy offline | CPU |

**Chuỗi dự phòng đề xuất** (tool tự chuyển, người dùng không phải làm gì):

```
API (Gemini/Z.ai/…)  →  AI local (Ollama)  →  Chế độ Không AI (luật)
```

Tool **luôn ra được video**, chỉ khác chất lượng chọn meme và chia câu.

---

## 1. Hiện trạng tool: bước nào cần AI

| Bước | Hiện tại khi không có API | Ghi chú |
|---|---|---|
| Đọc chữ từ ảnh (OCR) | ❌ **Báo lỗi, bắt nhập key hoặc tự gõ chữ** | Đây là chỗ chặn chính, phải làm |
| Lấy bài từ link Threads | ✅ Không cần AI | Chữ lấy thẳng từ dữ liệu trang |
| Lọc bình luận hay | ⚠️ Có dự phòng: lấy theo lượt thích | AI local giúp chọn hay hơn |
| Chia câu + chọn meme | ⚠️ Có planner dự phòng | Chọn meme theo từ khóa còn yếu |
| Caption, hashtag, chủ đề tên file | ⚠️ Có dự phòng: lấy tiêu đề hoặc 8 từ đầu | AI local cho kết quả tự nhiên hơn |
| Gắn nhãn meme | ❌ Cần AI đọc ảnh | Có thể làm bằng model đọc ảnh local, hoặc gõ tay |
| Giọng đọc | ✅ VieNeu-TTS offline đã có | Edge-TTS thì cần mạng |

---

## 2. Ba hướng kỹ thuật

### Hướng A: Ollama (AI chạy trên máy, khuyến nghị chính)

- **Ollama** là phần mềm miễn phí chạy model AI trên máy. Trên Windows, nó chạy như ứng dụng gốc, hỗ trợ card NVIDIA và AMD Radeon. Yêu cầu Windows 10 22H2 trở lên.
- **Điểm hay nhất:** Ollama có cổng **giống hệt API của OpenAI** tại `http://localhost:11434/v1`. Tool đã có sẵn class "tương thích OpenAI" (dùng cho Z.ai và OpenRouter), nên **chỉ cần thêm nhà cung cấp "Ollama (máy này)"** với Base URL đó. API key nhập bừa vẫn được, vì Ollama bỏ qua key.
- Cổng này hỗ trợ: chat, chế độ JSON, đọc ảnh (vision).
- Thay thế tương đương: **LM Studio** (có giao diện, cổng `http://localhost:1234/v1`). Tool nên hỗ trợ cả hai qua ô Base URL.

**Model nên dùng (tên lệnh Ollama):**

| Vai trò | Model | Ghi chú |
|---|---|---|
| Chữ: chia câu, chọn meme, caption | `qwen3:4b` (nhẹ, nhanh) / `qwen3:8b` (hay hơn) | Qwen3 mạnh đa ngôn ngữ, tiếng Việt tốt trong nhóm model nhỏ |
| Chữ (thay thế) | `gemma3:4b` / `gemma3:12b` | Gemma đa ngôn ngữ tốt, bản 4B có đọc ảnh |
| Đọc ảnh (gắn nhãn meme, OCR dự phòng) | `qwen3-vl:2b` (máy yếu) / `qwen3-vl:8b` (card 8 GB) | Qwen3-VL đang là model đọc ảnh local mạnh nhất cho OCR và ảnh chụp màn hình |
| OCR chuyên dụng (thử nghiệm) | `glm-ocr`, `deepseek-ocr` | Có trên Ollama, cần thử trên ảnh tiếng Việt thật |

### Hướng B: OCR chuyên dụng offline (cho bước đọc ảnh)

- **Phát hiện quan trọng:** model AI đọc ảnh (VLM) **không phải lúc nào cũng đọc chữ chính xác hơn OCR truyền thống.** Một bộ kiểm thử tiếng Việt ghi nhận `qwen2.5vl:7b` sai khoảng **31% ký tự** trên dòng chữ in rõ, trong khi Tesseract chỉ sai khoảng **5%**. VLM giỏi *hiểu* tài liệu, còn chép từng chữ chính xác thì OCR chuyên dụng tốt hơn.
- Ảnh thẻ Threads là **chữ in rõ trên nền trắng**, đúng sở trường của OCR chuyên dụng.
- **PaddleOCR PP-OCRv5**:
  - Model nhận dạng đa ngôn ngữ, **có tiếng Việt** (nhóm chữ Latin, mã `vi`).
  - Bản mobile chỉ khoảng **5 triệu tham số**, độ chính xác ngang các VLM hàng tỷ tham số trên bộ kiểm thử OCR chuẩn.
  - Chạy tốt bằng CPU, cài qua `pip install paddleocr`.
- **VietOCR**: thư viện OCR chuyên cho tiếng Việt (kiến trúc Transformer), thường ghép với bộ dò dòng chữ của PaddleOCR.
- **Tesseract** (gói `vie`): cũ hơn nhưng nhẹ, dễ cài, làm phương án cuối.

**Cách ghép đề xuất cho bước OCR:**
1. Tool đã cắt sẵn thẻ trắng (OpenCV).
2. **PaddleOCR** đọc ra các dòng chữ kèm tọa độ.
3. Dùng **luật** bỏ dòng tên, thời gian ("6 giờ"), "Thành viên cộng đồng", "1/7", logo. Có tọa độ nên biết dòng nào là header, dòng nào là thân bài. Dòng tọa độ header này cũng dùng để che tên.
4. *(Tùy chọn)* Đưa chữ đã đọc cho **AI chữ local** (Qwen3) sửa lỗi dấu và nối dòng bị ngắt. Có ảnh để đối chiếu thì dùng Qwen3-VL.
5. Hiện chữ cho người dùng sửa như hiện nay.

### Hướng C: Chế độ "Không AI" (luật, luôn chạy được)

- **Tách câu:** đã có `split_sentences` trong `textnorm.py`.
- **Chọn meme theo từ khóa:**
  - Mỗi meme có nhãn (`khinh bỉ`, `sốc`, `khóc`…). Thêm **từ điển cảm xúc tiếng Việt**, ví dụ:
    - `haha, buồn cười, lol` → cười
    - `trời ơi, hả, sao lại` → sốc
    - `tội, thương, khóc` → buồn
  - Câu nào khớp từ khóa thì gán meme có nhãn tương ứng, kèm luật mật độ (không 2 câu liền nhau, không lặp quá 2 lần).
- **Lọc bình luận:** đã có (lấy theo lượt thích sau khi lọc rác).
- **Chủ đề tên file và caption:** đã có dự phòng, bổ sung thêm mẫu câu caption ("Bạn nghĩ sao? Bình luận nhé!").

---

## 3. Chọn model theo cấu hình máy

| Cấu hình máy | Đọc chữ (OCR) | AI chữ | Đọc ảnh meme | Tốc độ ước tính / video |
|---|---|---|---|---|
| **Không card rời, RAM 8 GB** | PaddleOCR (CPU) | Chế độ Không AI, hoặc `qwen3:1.7b` | Gõ nhãn tay | OCR vài giây; AI rất chậm |
| **Không card rời, RAM 16 GB** | PaddleOCR (CPU) | `qwen3:4b` (CPU, chậm nhưng dùng được) | `qwen3-vl:2b` | 1–3 phút |
| **Card NVIDIA 6–8 GB** (RTX 3060/4060…) | PaddleOCR (+ sửa bằng AI) | `qwen3:8b` | `qwen3-vl:8b` | khoảng 20–60 giây |
| **Card NVIDIA 12 GB trở lên** | PaddleOCR + `qwen3-vl:8b` kiểm tra lại | `qwen3:14b` hoặc `gemma3:12b` | `qwen3-vl:8b` | nhanh |
| **Card AMD** | PaddleOCR (CPU) | Ollama hỗ trợ Radeon trên Windows; nếu không nhận card thì tự chạy CPU | như trên | tùy |

Lưu ý:
- Model chạy bằng CPU thì **chậm**: một hướng dẫn 2026 ghi khoảng 2–8 token/giây với model 2B trở xuống.
- Model đọc ảnh tốn thêm 1–3 GB bộ nhớ so với model chỉ đọc chữ cùng cỡ, và sinh chữ chậm hơn.
- Mỗi model tải về tốn khoảng 1,5–6 GB ổ đĩa.

---

## 4. Thiết kế tích hợp vào tool

### 4.1 Cài đặt (trang Cài đặt → AI)
- Thêm lựa chọn nhà cung cấp **"🖥️ AI trên máy (Ollama)"**:
  - Base URL mặc định `http://localhost:11434/v1`, không cần key.
  - Ô chọn **model chữ** và **model đọc ảnh**: tool gọi `GET /api/tags` để liệt kê model đã tải, kèm nút **"Tải model gợi ý"**, tương đương `ollama pull qwen3:4b`.
  - Nút **"Kiểm tra"**: báo Ollama đã chạy chưa, có card đồ họa không (`/api/ps`), chạy thử một câu JSON.
- Thêm **"Bộ đọc chữ (OCR)"**: `Tự động` / `PaddleOCR (offline)` / `AI đọc ảnh`.
  - `Tự động` = có API thì dùng API, không thì dùng PaddleOCR.
- Mục **Dự phòng** có sẵn: thêm lựa chọn "AI trên máy" và "Không AI".

### 4.2 Code (dựa trên cấu trúc hiện có)
- `app/llm/openai_llm.py`: thêm class `OllamaLLM(OpenAILLM)` với base URL `localhost:11434/v1`, không bắt key, `temperature` thấp, timeout dài (model local khởi động chậm).
- `app/config.py`: `has_llm()` coi Ollama là sẵn sàng khi gọi được `/api/tags`, không cần key.
- `app/pipeline/ocr_local.py` (mới): PaddleOCR với `lang="vi"`, trả về dòng chữ và tọa độ. Kèm luật bỏ header và tính vùng che tên.
- `app/pipeline/ocr.py`: chọn bộ đọc theo cài đặt, cùng định dạng kết quả như bản AI hiện nay.
- `app/pipeline/planner.py`: bản dự phòng chọn meme theo **từ điển cảm xúc** (Hướng C).
- `app/llm/factory.py`: chuỗi dự phòng `API → Ollama → Không AI` (đã có `FallbackLLM`, mở rộng thêm một tầng).
- `requirements.txt`: thêm `paddleocr` (và `paddlepaddle` bản CPU) làm **tùy chọn**. Cài bằng `run.bat --offline` hoặc nút trong Cài đặt, để người không cần thì không phải tải nặng.

### 4.3 Prompt cho model nhỏ
Model 4–8B kém hơn Gemini hay Claude nên cần:
- Prompt **ngắn hơn**, có **ví dụ mẫu JSON**, chia việc nhỏ (chia câu riêng, chọn meme riêng).
- Gửi danh sách meme **rút gọn** (tên + 3 nhãn).
- Dùng chế độ **structured output** của Ollama (`format` = JSON schema ở API gốc `/api/chat`) để ép đúng định dạng.
- Kiểm tra lại bằng code như hiện nay (meme phải tồn tại, luật mật độ).

---

## 5. Những "bẫy" cần xử lý

1. **Chế độ suy nghĩ của Qwen3:** model có thể in phần suy nghĩ trước JSON, làm hỏng việc đọc JSON. Phải tắt (`think: false` hoặc `/no_think`), và giữ bộ tách JSON hiện có.
2. **Thiếu bộ nhớ card đồ họa (VRAM):** chạy song song model chữ và model ảnh có thể tràn. Nên gọi **tuần tự**, đặt `keep_alive` ngắn để nhả model sau khi dùng.
3. **Lần gọi đầu chậm:** nạp model mất 5–30 giây. Phải hiện "Đang khởi động AI trên máy…" và tăng thời gian chờ.
4. **Model đọc ảnh "bịa chữ"** trên dòng chữ cắt sát. Đây là lý do ưu tiên PaddleOCR cho chép chữ, dùng model ảnh chỉ để kiểm tra hoặc hiểu nội dung.
5. **Dấu tiếng Việt:** chuẩn hóa NFC sau OCR (tool đã có `unicodedata`). Có thể thêm bước sửa dấu bằng từ điển.
6. **Ollama chưa bật:** khi gặp lỗi kết nối tới `localhost:11434`, báo "Mở ứng dụng Ollama rồi thử lại", không báo lỗi khó hiểu.
7. **Card AMD trên Windows:** các hướng dẫn hiện còn nói khác nhau về việc Ollama có tự nhận card không. Nếu không nhận thì Ollama chạy CPU. Cần kiểm tra trên máy thật.

---

## 6. Ước lượng chất lượng so với API

| Việc | API (Gemini/Claude) | Ollama Qwen3 8B | Không AI |
|---|---|---|---|
| Chép chữ từ ảnh | Rất tốt | PaddleOCR: tốt với ảnh chụp màn hình rõ | PaddleOCR như cột bên |
| Chia câu tự nhiên | Rất tốt | Tốt | Khá (theo dấu câu) |
| Chọn meme hợp cảm xúc | Rất tốt | Khá–tốt | Trung bình (theo từ khóa) |
| Lọc bình luận hay | Rất tốt | Khá | Theo lượt thích |
| Caption, chủ đề | Rất tốt | Khá | Mẫu cố định |

---

## 7. Kế hoạch triển khai

| Giai đoạn | Nội dung | Kết quả |
|---|---|---|
| **1. Không AI vẫn ra video** | PaddleOCR thay bước OCR khi không có API, chọn meme theo từ điển cảm xúc | Không key vẫn làm được video từ ảnh |
| **2. Ollama** | Nhà cung cấp "AI trên máy", tự dò model, nút tải model, kiểm tra kết nối, tắt chế độ suy nghĩ | Chất lượng gần API, miễn phí |
| **3. Dự phòng 3 tầng** | API → Ollama → Không AI tự chuyển, ghi rõ trong nhật ký đang dùng tầng nào | Không bao giờ bị kẹt |
| **4. Gói cài một chạm** | `run.bat --offline` cài PaddleOCR; hướng dẫn cài Ollama trong README | Người không rành kỹ thuật cũng cài được |

**Tiêu chí nghiệm thu:**
- [ ] Rút mạng hoặc xóa hết API key: upload 2 ảnh mẫu vẫn ra video có giọng đọc (VieNeu), thẻ, meme.
- [ ] PaddleOCR đọc đúng ≥ 97% ký tự có dấu trên ảnh thẻ Threads mẫu, bỏ đúng tên, giờ, "1/7".
- [ ] Với Ollama `qwen3:8b`: JSON kế hoạch hợp lệ ≥ 95% số lần, meme đúng cảm xúc ở phần lớn câu.
- [ ] Ollama chưa mở: báo lỗi tiếng Việt dễ hiểu và tự chuyển sang Không AI.
- [ ] Nhật ký render ghi rõ: "Đọc chữ: PaddleOCR · AI: Ollama qwen3:8b".

---

## 8. Ưu và nhược điểm của phương án

**Ưu điểm:**
- Miễn phí, không giới hạn số video.
- Chạy được khi mất mạng.
- Dữ liệu không rời máy.
- Tận dụng gần như toàn bộ code hiện có (class tương thích OpenAI, `FallbackLLM`, các bản dự phòng).

**Nhược điểm:**
- Tốn ổ đĩa (vài GB cho model, khoảng 1 GB cho PaddleOCR).
- Máy không có card rời thì AI chậm.
- Chọn meme và caption kém tinh tế hơn API lớn.
- Phải cài thêm Ollama, một ứng dụng riêng.

---

## 9. Câu hỏi cần bạn trả lời ✍️

1. **Máy bạn có card đồ họa rời không?** Mở PowerShell, gõ `nvidia-smi`; nếu ra bảng thì gửi mình dòng tên card và bộ nhớ (vd "RTX 3060 12GB"). Hoặc mở Task Manager → Performance → GPU để xem.
2. **RAM bao nhiêu GB?** Xem ở Task Manager → Performance → Memory.
3. **Ổ đĩa còn trống bao nhiêu?** Cần khoảng 5–10 GB cho model.
4. Bạn muốn làm **giai đoạn 1** (không AI vẫn ra video, nhẹ nhất) trước, hay làm luôn **Ollama**?
5. Có chấp nhận **cài thêm ứng dụng Ollama** không, hay muốn mọi thứ nằm gọn trong tool?

---

## Nguồn tham khảo
- Ollama: tương thích OpenAI API (chat, JSON mode, vision): https://docs.ollama.com/openai
- Ollama trên Windows (yêu cầu hệ thống, hỗ trợ NVIDIA/AMD): https://docs.ollama.com/windows
- Danh sách model Ollama (glm-ocr, deepseek-ocr, qwen…): https://registry.ollama.ai/models
- So sánh model đọc ảnh chạy local theo cấp card đồ họa (Qwen3-VL, Gemma 3): https://insiderllm.com/guides/vision-models-locally/
- PP-OCRv5 đa ngôn ngữ, có tiếng Việt: https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
- Bài báo PP-OCRv5 (5M tham số, ngang VLM tỷ tham số): https://arxiv.org/pdf/2603.24373
- Ghi chú kiểm thử OCR tiếng Việt (VLM vs Tesseract): https://tomevault.io/tome/nrl-ai/nom-vn
- Khảo sát OCR tiếng Việt (thách thức về dấu, Vintern-1B): https://arxiv.org/html/2506.05061v1
- VietOCR + PaddleOCR cho tiếng Việt: https://github.com/bmd1905/vietnamese-ocr
- Model local theo dung lượng RAM (Qwen3, Gemma): https://frankx.ai/blog/best-local-llm-2026
- Chạy LLM trên Windows (yêu cầu tối thiểu, tốc độ CPU): https://llmhardware.io/guides/how-to-run-llms-on-windows

---

## 10. Quyết định cho máy của bạn (GTX 1660 Ti 6 GB, RAM 16 GB) — đã triển khai 31/10/2026

- **Model:** `qwen3.5:4b` (~3,4 GB). Một model làm cả **đọc ảnh** lẫn **chữ**, nên không phải đổi qua lại 2 model trên card 6 GB. Qwen3.5 tốn rất ít bộ nhớ cho ngữ cảnh, nên đặt `num_ctx = 16384` vẫn vừa card.
- **Không chọn** `qwen3.5:9b` (6,6 GB, tràn card 6 GB, phải chạy một phần bằng CPU nên chậm) và cũng không dùng 2 model riêng (`qwen3:4b` + `qwen3-vl:4b`).
- **Gọi Ollama qua API gốc `/api/chat`:** `think: false` (tắt suy nghĩ), `format: "json"`, `keep_alive: 15m`, ảnh thu về cạnh dài 1400 px, xử lý tuần tự từng thẻ.
- **PaddleOCR/RapidOCR: tạm hoãn.** Tool chạy Python 3.14 nên gói PaddlePaddle chưa chắc có bản cài; qwen3.5:4b đọc cả thẻ ảnh trên card đồ họa là đủ dùng. Sẽ xem lại nếu chữ đọc sai nhiều.
- **Chế độ không AI** khi Ollama tắt: chọn meme theo từ điển cảm xúc tiếng Việt, khớp nguyên từ.
- **File đã thêm/sửa:** `app/llm/ollama.py` (mới), `app/llm/factory.py`, `app/config.py`, `app/main.py` (API `/api/ollama/status`, `/api/ollama/pull`), `app/pipeline/ocr.py`, `app/pipeline/planner.py`, `app/static/settings.html`, `requirements.txt`, `README.md`.
