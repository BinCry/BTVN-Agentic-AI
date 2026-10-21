# Challenge A — Persistent Memory

Một harness agent tối giản, chạy hoàn toàn offline bằng Python standard library. Bài làm tập trung đúng Challenge A trong slide: memory dự án phải còn qua session mới, quy ước mới phải thay thế quy ước đang hiệu lực, và phần memory được inject vào context phải nhìn thấy được.

Yêu cầu: Python 3.11 trở lên; không cần cài package nào.

## Thiết kế

- **Lưu ở đâu:** `data/memory.json` là persistent store; `data/memory-audit.jsonl` là nhật ký append-only để kiểm tra lịch sử thay đổi.
- **Ai ghi:** lệnh `remember` của harness ghi một quy ước đã được người dùng/agent thống nhất.
- **Khi nào nạp:** mỗi lệnh `ask` đọc **chỉ** các quy ước `active`, tạo payload JSON, rồi **luôn** in nó trong khối `INJECTED_MEMORY` trước khi tạo câu trả lời.
- **Khi quy ước đổi:** bản active cũ được đánh dấu `superseded` và liên kết `superseded_by`; bản mới trở thành active. Lịch sử không bị xóa, nhưng bản cũ không được inject.

Đây là JSON có version vì dễ kiểm tra trong timebox 30 phút. Khi project lớn hơn, `active_conventions()` có thể là index nhỏ và load thêm topic file/SQLite theo nhu cầu (progressive disclosure).

## Khi nào ghi memory?

`remember` là memory-write tool mà agent/harness gọi khi người dùng **chốt** hoặc **đổi** một thông tin bền vững: ví dụ “API dùng camelCase” hoặc “từ giờ đổi sang snake_case”. Không ghi mọi câu chat, log test, hay thử nghiệm chưa kết luận. Quy ước active luôn là nguồn đúng cho session sau; bản thay thế chỉ còn trong audit.

## Chạy phần chứng minh

Từ PowerShell, tại thư mục bài làm:

```powershell
python demo.py
```

Demo chạy bốn session độc lập:

1. `day-1` thống nhất `api_field_style = camelCase`.
2. `day-2` là session mới, in memory đã inject và trả lời dùng `userId`, `createdAt`.
3. `day-3` đổi quy ước sang `snake_case`.
4. `day-4` là session mới, chỉ nhận version mới trong injected memory và dùng `user_id`, `created_at`.

Sau đó mở `demo-output/memory.json` để thấy bản v1 là `superseded`, v2 là `active`; `demo-output/memory-audit.jsonl` giữ audit trail. Demo chỉ reset thư mục `demo-output`; không đụng vào kho `data/` của CLI.

## Dùng CLI

```powershell
python memory_harness.py remember --store data/memory.json --topic api_field_style --value camelCase --session day-1
python memory_harness.py ask --store data/memory.json --session day-2 --task "Create a user endpoint"
python memory_harness.py remember --store data/memory.json --topic api_field_style --value snake_case --session day-3
python memory_harness.py ask --store data/memory.json --session day-4 --task "Create a user endpoint"
```

`ask` nhận response từ đúng JSON payload đã in, không đọc store lần nữa trong lúc trả lời. Vì vậy output chứng minh memory đã được inject vào context, thay vì chỉ tình cờ còn nằm trên đĩa.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

Các test xác nhận persistence qua session, injected payload ở session mới, thay thế convention có audit linkage, và response dùng đúng active convention.
