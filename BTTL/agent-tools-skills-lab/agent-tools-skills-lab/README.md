# Agent Tools & Skills Lab

Lab Python gồm 5 stage tăng dần khả năng của một LangChain agent có giao diện chat Streamlit và panel **State & Context**. Mỗi stage có source, cấu hình, workspace, trace và tests độc lập; cả lab dùng chung một uv workspace (`.venv` và `uv.lock` ở thư mục này).

| Stage | Khả năng bổ sung | Tools | Skills có sẵn |
|---|---|---|---|
| [`stage-00-chat`](stage-00-chat/README.md) | Chat cơ bản | Không có | Không có |
| [`stage-01-files`](stage-01-files/README.md) | Đọc, ghi và liệt kê file | `list_files`, `read_file`, `write_file` | Không có |
| [`stage-02-skills`](stage-02-skills/README.md) | Catalog skill, model tự đọc skill khi cần | `list_files`, `read_file`, `write_file` | `weekly-report`, `refund-policy` |
| [`stage-03-bash`](stage-03-bash/README.md) | Chạy lệnh ngắn trong workspace | `read_file`, `write_file`, `bash` | `weekly-report` |
| [`stage-04-script-skill`](stage-04-script-skill/README.md) | Skill có script kiểm tra CSV | `read_file`, `write_file`, `bash` | `weekly-report`, `csv-quality` |

Xem khác biệt chi tiết giữa các stage tại [STAGE-DIFFS.md](STAGE-DIFFS.md) và kết quả xác minh tại [verification.md](verification.md).

## Yêu cầu và an toàn

- Python **3.11+** và [uv](https://docs.astral.sh/uv/).
- API key của provider OpenAI hoặc endpoint tương thích OpenAI Chat Completions có hỗ trợ **native tool calling**.
- `stage-03-bash` và `stage-04-script-skill` cần môi trường POSIX có `bash`. Trên Windows, dùng **WSL2** để chạy hai stage này.

> **Chỉ dành cho lab.** Tool `bash` chạy lệnh với quyền của người đang chạy app. CWD và môi trường tối thiểu không phải sandbox; lệnh vẫn có thể tác động ngoài `workspace/`. Chỉ dùng dữ liệu giả của lab, không dùng trên máy chủ hay dữ liệu nhạy cảm.

## Cài đặt chung

Từ thư mục `agent-tools-skills-lab`, cài dependency cho cả năm stage một lần:

```bash
uv sync --all-packages --locked
```

Vào stage muốn chạy, ví dụ Stage 02:

```bash
cd stage-02-skills
```

Tạo `.env` từ template của stage. Template chỉ chứa tên biến, không chứa credential.

**POSIX (Linux/macOS/WSL2):**

```bash
cp -n .env.example .env
```

**Windows PowerShell:**

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Mở `.env` và tự điền các giá trị cục bộ sau; không commit hoặc chia sẻ file này:

| Biến | Bắt buộc | Mô tả |
|---|---|---|
| `OPENAI_API_KEY` | Có | API key của provider |
| `MODEL_NAME` | Có | Model hỗ trợ native tool calling |
| `OPENAI_BASE_URL` | Không | Endpoint tương thích OpenAI Chat Completions |

Khi dùng `OPENAI_BASE_URL`, endpoint phải hỗ trợ `tools`, `tool_calls` và message role `tool`. Nếu thiếu `OPENAI_API_KEY` hoặc `MODEL_NAME`, app chỉ hiện cảnh báo và khóa ô chat, không gọi model. App không hard-code credential hoặc model và không ghi API key vào trace/log.

## Chạy, test và reset từng stage

Sau khi đã vào thư mục của stage, dùng các lệnh trong bảng. Streamlit in **Local URL** (mặc định `http://localhost:8501`) trên terminal.

| Stage | Chạy app | Test | Reset dữ liệu |
|---|---|---|---|
| `stage-00-chat` | `uv run streamlit run app.py` | `uv run pytest` | Không áp dụng |
| `stage-01-files` | `uv run streamlit run app.py` | `uv run pytest` | `uv run python reset_workspace.py` |
| `stage-02-skills` | `uv run streamlit run app.py` | `uv run pytest` | `uv run python reset_workspace.py` |
| `stage-03-bash` | `uv run streamlit run app.py` | `uv run pytest` | `uv run python reset_workspace.py` |
| `stage-04-script-skill` | `uv run streamlit run app.py` | `uv run pytest` | `uv run python reset_workspace.py` |

Tests dùng mock model nên không cần API key. Nếu cần chạy từ root lab thay vì `cd` vào stage, truyền project rõ ràng, ví dụ:

```bash
uv run --project stage-02-skills streamlit run stage-02-skills/app.py
```

Muốn chạy nhiều app cùng lúc, thêm `--server.port 8502` (và các port khác) vào lệnh của app tiếp theo.

## Cấu trúc và dữ liệu thực hành

```text
agent-tools-skills-lab/
├── pyproject.toml             # uv workspace của 5 stage
├── uv.lock
├── stage-00-chat/
├── stage-01-files/
├── stage-02-skills/
├── stage-03-bash/
└── stage-04-script-skill/
    ├── .env.example           # template cấu hình, không có secret
    ├── fixtures/              # dữ liệu gốc để khôi phục
    ├── workspace/             # dữ liệu làm việc của agent
    ├── traces/                # trace JSONL theo từng lượt
    └── tests/
```

Stage 01–04 khởi tạo `workspace/` từ `fixtures/` khi chưa có workspace. Agent chỉ đọc file trong workspace và chỉ ghi qua `write_file` vào `workspace/output/`. Lệnh reset khôi phục fixture, xóa output đã sinh và giữ lại trace; lệnh chỉ chấp nhận workspace có marker `.lab-workspace`.

Stage 02–04 quét `workspace/skills/*/SKILL.md` để đưa metadata (`name`, `description`, `location`) vào catalog ban đầu. Nội dung thân skill và reference không tự vào context: model phải gọi `read_file` khi task phù hợp. Stage 04 dùng skill `csv-quality` để chạy script kiểm tra `data/tasks.csv` và tạo báo cáo trong `output/`.

## Quan sát quá trình chạy

- Mỗi stage có `traces/` riêng. Mỗi lượt sinh một file JSONL chứa event theo thứ tự, gồm model request/response, tool call, thời gian chạy và snapshot context trước mỗi lần gọi model.
- Panel **State & Context** hiển thị trạng thái, bộ đếm model/tool call, catalog skill, skill/tài nguyên đã đọc, message history và event log. Có thể xem hoặc tải snapshot context cũ mà không chạy lại agent.
- Nút **Cuộc trò chuyện mới** chỉ xóa state trong bộ nhớ; trace trên đĩa và file output (nếu stage có workspace) vẫn được giữ lại.
- Exception không mong đợi được ghi thêm vào `traces/debug.log`; API key không được ghi vào trace hoặc log.

## Chạy một stage độc lập

Mỗi `stage-*` có `pyproject.toml`, source, fixture, workspace và tests riêng. Khi copy một stage ra ngoài lab, dùng `uv sync` tại thư mục đã copy để tạo môi trường/lockfile độc lập, sau đó tạo `.env` từ `.env.example` và chạy `uv run streamlit run app.py`.
