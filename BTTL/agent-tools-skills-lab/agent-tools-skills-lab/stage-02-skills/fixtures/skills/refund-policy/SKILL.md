---
name: refund-policy
description: Tra cứu và áp dụng chính sách hoàn tiền theo ngày mua, ngày yêu cầu hoàn và trạng thái kích hoạt sản phẩm.
---

# Tra cứu chính sách hoàn tiền

Dùng skill này khi người dùng hỏi có đủ điều kiện hoàn tiền, chính sách nào áp dụng hoặc phí hoàn tiền cho một đơn hàng.

## Thông tin bắt buộc

Trước khi kết luận, cần có đủ ba thông tin: ngày mua, ngày yêu cầu hoàn và trạng thái sản phẩm đã kích hoạt hay chưa. Nếu thiếu bất kỳ thông tin nào, chỉ hỏi lại thông tin còn thiếu; không tự giả định và không kết luận.

## Quy trình

1. Đọc `references/answer-template.md` để lấy cấu trúc câu trả lời.
2. Dùng `list_files` với `data/policies/` để tìm tài liệu chính sách hiện có. Không giả định tên file.
3. Đọc các file chính sách được tìm thấy bằng `read_file`. Xác định phạm vi hiệu lực từ nội dung tài liệu và chọn chính sách dựa trên **ngày mua**.
4. Tính số ngày lịch giữa ngày yêu cầu hoàn và ngày mua. Bằng đúng giới hạn trong chính sách vẫn đạt điều kiện về thời gian.
5. Áp dụng điều kiện về kích hoạt và phí theo chính sách đã chọn. Luôn nêu đường dẫn file đã đọc làm căn cứ.

Không dùng Bash hoặc script: stage này chỉ có các tool quản lý file.
