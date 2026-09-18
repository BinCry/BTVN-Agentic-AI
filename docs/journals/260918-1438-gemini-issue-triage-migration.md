---
date: 2026-09-18
session: gemini-issue-triage-migration
---

# Journal: 2026-09-18 — Gemini Issue Triage Migration

## Context

Chuyển bộ demo Issue Triage sang Google AI Studio để chạy bằng Gemini API key cục bộ, đồng thời giữ đúng các nội dung trong `demo-guide.html`.

## What Changed

- Chuẩn hoá các demo 00–04 theo Google GenAI SDK, dùng cấu hình chung và `.env` cục bộ.
- Bổ sung structured output Pydantic, kiểm tra output ở application, và function-calling trace có validate tool/arguments trước khi tra owner component.
- Thêm giao diện Streamlit, requirements và hướng dẫn chạy; cache tokenizer được giới hạn trong thư mục demo.

## Verification

- `Demo Issue Triage/.venv/Scripts/python.exe -m py_compile` chạy thành công cho toàn bộ source Python của demo.
- Các lệnh gọi Gemini thực tế vẫn cần một `GEMINI_API_KEY` hợp lệ trong `.env` và quota/model được cấp ở Google AI Studio.

## Decision

| Decision | Rationale | Impact |
|---|---|---|
| Dùng `google-genai` với `GEMINI_API_KEY` trong `.env` không được theo dõi | Tương thích Google AI Studio và không đưa bí mật vào source | Người dùng chỉ cần cấu hình key cục bộ trước khi chạy demo |

## Next

- Tạo `.env` từ `.env.example`, chạy lần lượt demo CLI và `streamlit run 04_streamlit_triage.py`.
- Lưu ảnh kết quả chạy để nộp cùng link source code.
