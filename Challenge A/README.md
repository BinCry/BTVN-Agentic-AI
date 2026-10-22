# Challenge A — Persistent Memory

Harness memory bền vững cho agent bằng Python standard library. Chế độ mặc định chạy hoàn toàn offline; khi có `GEMINI_API_KEY`, cùng CLI có thể gọi Gemini thật để chứng minh memory đã được đưa vào prompt của LLM.

Yêu cầu: Python 3.11 trở lên; không cần cài package nào. API key chỉ cần cho `--provider gemini`.

## Thiết kế

- **Lưu ở đâu:** `data/memory.json` là persistent store; `data/memory-audit.jsonl` là nhật ký append-only để kiểm tra lịch sử thay đổi.
- **Versioning:** một convention active mới sẽ đánh dấu bản active cũ là `superseded` và thêm liên kết `superseded_by`. Bản cũ luôn ở audit nhưng không được inject.
- **Retrieval:** `ask` mặc định chọn tối đa ba convention active liên quan đến từ khóa trong task. Nếu project chỉ có đúng một convention active, harness vẫn giữ nó khi không có keyword trùng để có context khởi đầu hữu ích. Có thể chọn chính xác bằng `--memory-topic`, hoặc dùng `--all-active-memory` khi cần xem toàn bộ.
- **Offline:** `agent_response()` là stub xác định để demo và test tái lập được mà không cần mạng/key.
- **Gemini:** `--provider gemini` gửi *nguyên văn* khối `INJECTED_MEMORY` đã in ra vào prompt `generateContent`. Test mock xác nhận chuỗi prompt này chứa chính xác payload đã hiển thị.
- **Memory write:** Gemini chỉ có thể *đề xuất* gọi `remember_convention`. Harness chỉ cho phép ghi khi người dùng đã thêm `--allow-memory-write`, kiểm tra topic/value trước khi gọi `MemoryStore.record`, và chặn credential-shaped data. Lệnh `remember` thủ công vẫn luôn có sẵn và dùng cùng kiểm tra bí mật.

## Chạy demo offline

Từ PowerShell tại thư mục bài làm:

```powershell
python demo.py
```

Demo chạy bốn session độc lập:

1. `day-1` lưu ba convention: `api_field_style = camelCase`, database PostgreSQL migrations và authentication JWT bearer.
2. `day-2` là session mới; retrieval chọn ba convention phù hợp với task PostgreSQL API dùng JWT.
3. `day-3` đổi `api_field_style` sang `snake_case`.
4. `day-4` là session mới; injected memory chỉ có API style v2, database và authentication vẫn là các revision active.

Sau đó mở `demo-output/memory.json` để thấy API style v1 là `superseded`, v2 là `active`; `demo-output/memory-audit.jsonl` giữ audit trail. Demo chỉ reset `demo-output/`, không đụng vào kho `data/` của CLI.

## Dùng CLI offline

```powershell
python memory_harness.py remember --store data/memory.json --topic api_field_style --value camelCase --session day-1
python memory_harness.py remember --store data/memory.json --topic database_migration_style --value "PostgreSQL migrations" --session day-1
python memory_harness.py remember --store data/memory.json --topic authentication_scheme --value "JWT bearer" --session day-1
python memory_harness.py ask --store data/memory.json --session day-2 --task "Create a PostgreSQL API endpoint protected by JWT"
```

`ask` luôn in `INJECTED_MEMORY` trước `AGENT_RESPONSE`. Không có key, provider mặc định là `offline` nên không gọi mạng hay phát sinh chi phí.

### Kiểm soát retrieval

```powershell
# Chỉ giữ tối đa hai convention liên quan theo keyword trong task
python memory_harness.py ask --store data/memory.json --session day-2 --task "Create a PostgreSQL API endpoint" --max-memory-items 2

# Chọn chính xác topic, có thể lặp lại flag
python memory_harness.py ask --store data/memory.json --session day-2 --task "Create an endpoint" --memory-topic api_field_style --memory-topic authentication_scheme

# Chủ động inject tất cả active convention để kiểm tra/audit
python memory_harness.py ask --store data/memory.json --session day-2 --task "Review project conventions" --all-active-memory
```

## Chạy với Gemini thật

Sao chép cấu hình mẫu và đặt key lấy từ [Google AI Studio](https://aistudio.google.com/app/apikey):

```powershell
Copy-Item .env.example .env
```

Sửa `.env` cục bộ, không commit file này:

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

Sau khi đã có convention, gọi Gemini bằng `--provider gemini`:

```powershell
python memory_harness.py ask --store data/memory.json --session day-2 --task "Create a PostgreSQL API endpoint protected by JWT" --provider gemini
```

Khi người dùng xác nhận thay đổi bền vững, Gemini có thể gọi tool an toàn `remember_convention`; harness mới thực sự ghi revision. Ví dụ:

```powershell
python memory_harness.py ask --store data/memory.json --session day-3 --task "Từ giờ API phải dùng snake_case; hãy lưu quy ước này." --provider gemini --allow-memory-write
```

Gemini được gọi qua REST `generateContent`, dùng header `x-goog-api-key`; key không được thêm vào URL, output hoặc audit. Xem [Gemini Generate Content API](https://ai.google.dev/api/generate-content) và [function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling) để biết giao thức.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

Test không gọi mạng thật. Chúng xác nhận persistence qua session, supersession/audit, retrieval theo task, prompt Gemini chứa đúng payload đã in, function call chỉ ghi khi có opt-in, và credential không thể đi vào store hoặc audit.
