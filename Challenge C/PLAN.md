# Kế hoạch triển khai Challenge C

## Phạm vi

Tạo một mô phỏng Python 3 độc lập, chỉ dùng standard library, cho Cache-Aware Model Router. Mọi mã nguồn, kiểm thử và tài liệu đều nằm trong thư mục này.

## Các bước

1. Xây dựng engine giá bằng `Decimal` và mô hình cache/keep-alive có TTL cấu hình được.
2. Tính ba chiến lược Warm A, Cold & Compact (chọn A/B rẻ hơn), Switch B; retry được mô hình hóa là tối đa một lần lặp lại theo xác suất.
3. Thêm router, ba scenario bắt buộc, expected-cost cho phân bố uniform có điều kiện và phân tích break-even theo return probability.
4. Cung cấp CLI in bảng so sánh/ASCII bar, README tiếng Việt và tests dùng `unittest`.

## Ràng buộc

- Không sửa tệp bên ngoài `Challenge C`.
- Không cài package, không gọi API, không tạo virtual environment hay dữ liệu lớn.
- Xác nhận baseline $0.055 và $0.057 bằng test tự động.
