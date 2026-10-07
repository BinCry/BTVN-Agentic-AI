# Phân tích bài tập: Tra cứu chính sách đúng phiên bản

## Phạm vi hoàn thành

- `list_files(path)` đã được thêm vào Stage 01 và Stage 02. Tool chỉ liệt kê trực tiếp, sắp xếp theo tên, trả đường dẫn tương đối workspace và chặn đường dẫn/symlink thoát workspace.
- Stage 02 có skill `refund-policy`. Skill yêu cầu tìm tài liệu tại `data/policies/` bằng `list_files`, nên không phụ thuộc tên file.
- Hai chính sách nguồn được đặt ở cả `fixtures/` và `workspace/` để vẫn còn sau khi reset workspace.

## Kết quả cần xác nhận khi có model key

| Tình huống | Kết quả mong đợi |
| --- | --- |
| Mua 28/09/2026, hoàn 06/10/2026, chưa kích hoạt | Chính sách cũ; 8 ngày; không đủ điều kiện. |
| Mua 02/10/2026, hoàn 12/10/2026, chưa kích hoạt | Chính sách mới; 10 ngày; đủ điều kiện; không phí. |
| Thiếu trạng thái kích hoạt | Agent hỏi lại, không kết luận. |
| Đổi tên hai file policy và bắt đầu chat mới | Agent vẫn tìm bằng `list_files` và kết luận không đổi. |

## Kiểm tra đã chạy

- Test offline trên Windows: Stage 00 **17 passed**, Stage 01 **36 passed**, Stage 02 **44 passed**, Stage 03 **48 passed**, Stage 04 **61 passed**.
- Stage 02 Streamlit khởi động thành công tại `http://localhost:8501` (health check `ok`).
- Cả năm stage đã có cấu hình local cho Groq và model `openai/gpt-oss-20b`. Kiểm tra live bị chặn trước khi xác thực model bởi `HTTP 403`, provider message `error code: 1010`; cần chạy từ mạng/IP được Groq cho phép trước khi tạo trace live.

## Bằng chứng cần nộp sau khi chạy live

Mỗi lượt chạy tạo trace JSONL trong `traces/`. Lưu trace cho hai trường hợp đủ dữ liệu, trường hợp đổi tên file và trường hợp thiếu thông tin. Không đưa `.env` hoặc API key vào bài nộp.

## Trả lời câu hỏi cuối bài

Tool tìm file cung cấp khả năng quan sát workspace thực tế, nên agent vẫn xác định được tài liệu sau khi đổi tên. Skill biến khả năng đó thành quy trình lặp lại được: kiểm tra dữ kiện, tìm tài liệu, chọn phạm vi hiệu lực theo ngày mua và trả lời theo một cấu trúc thống nhất. Chỉ sửa prompt không thể cho agent biết tên/đường dẫn tài liệu mới nếu agent không có tool để khám phá filesystem.
