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
