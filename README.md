# BTVN Agentic AI

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/Gemini-Google_Gen_AI-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/gemini-api/docs)
[![License](https://img.shields.io/badge/License-Educational-green?style=for-the-badge)](https://github.com/BinCry/BTVN-Agentic-AI)

Kho lưu trữ bài tập thực hành của khóa học **Agentic AI**. Mỗi thư mục BTVN là một bài độc lập, có hướng dẫn cài đặt và cách chạy riêng.

---

## Danh sách bài tập

| Buổi | Thư mục | Chủ đề | Công nghệ / nội dung chính |
| --- | --- | --- | --- |
| 02 | [BTVN02/](./BTVN02/) | Agentic AI Issue Triage | Gemini, đo token bằng tiktoken, Pydantic structured output, function calling có kiểm soát, Streamlit |
| 03 | [BTVN03/](./BTVN03/) | Agent đặt vé máy bay bằng LangChain | ReAct, Plan-then-Execute, mẫu Lai, mock tools và harness kiểm soát agent |
| BTTL | [BTTL/agent-tools-skills-lab/agent-tools-skills-lab/](./BTTL/agent-tools-skills-lab/agent-tools-skills-lab/) | Agent Tools & Skills Lab | Python 3.11+, LangChain, Streamlit, uv, native tool calling |

---

## Cấu trúc repository

```text
BTVN-Agentic-AI/
├── BTVN02/                              # Bài 02: Issue Triage với Gemini
│   ├── 00_minimal_triage.py             # Gọi Gemini cơ bản
│   ├── 01_measure_tokens.py             # Đo token tiếng Anh và tiếng Việt
│   ├── 02_structured_output.py          # Structured output với Pydantic
│   ├── 03_function_calling.py           # Function calling có kiểm soát
│   ├── 04_streamlit_triage.py           # Giao diện Streamlit
│   ├── demo_common.py                   # Cấu hình Gemini dùng chung
│   ├── triage_workflow.py               # Luồng triage và kiểm tra tool call
│   ├── requirements.txt                 # Phụ thuộc của BTVN02
│   ├── .env.example                     # Mẫu biến môi trường cho Gemini
│   └── README.md                        # Hướng dẫn chi tiết BTVN02
├── BTVN03/                              # Bài 03: Agent đặt vé máy bay
│   ├── flight_agent.py                  # ReAct + harness
│   ├── flight_agent_plan_then_execute.py # Plan-then-Execute
│   ├── flight_agent_hybrid.py           # Mẫu Lai: plan, execute, ReAct recovery
│   ├── flight_agent_failure_mode.py     # Failure modes và harness fixes
│   └── BaoCao_BTVN03_Agent_Dat_Ve_May_Bay.pdf
├── BTTL/                                # Bài tập tại lớp: Agent Tools & Skills Lab
│   └── agent-tools-skills-lab/
│       └── agent-tools-skills-lab/
│           ├── README.md
│           ├── pyproject.toml
│           ├── uv.lock
│           ├── stage-00-chat/
│           ├── stage-01-files/
│           ├── stage-02-skills/
│           ├── stage-03-bash/
│           └── stage-04-script-skill/
├── .gitignore
└── README.md
```

---

## Bắt đầu nhanh

Clone repository và mở PowerShell tại thư mục gốc:

```powershell
git clone https://github.com/BinCry/BTVN-Agentic-AI.git
cd BTVN-Agentic-AI
```

### BTVN02 — Issue Triage với Gemini

BTVN02 yêu cầu Python 3.10 trở lên và Google AI Studio API key.

```powershell
cd BTVN02
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mở `.env` và điền API key của bạn:

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

Chạy các demo từ thư mục `BTVN02`:

```powershell
python 00_minimal_triage.py
python 01_measure_tokens.py
python 02_structured_output.py
python 03_function_calling.py
streamlit run 04_streamlit_triage.py
```

Xem [README của BTVN02](./BTVN02/README.md) để biết mô tả từng demo và các tùy chọn dòng lệnh.

### BTVN03 — Agent đặt vé máy bay bằng LangChain

BTVN03 dùng dữ liệu mockup và fake model được lập kịch bản. Bài này **không cần API key, file `.env` hay kết nối mạng**.

Từ thư mục gốc repository, cài môi trường và phụ thuộc:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "langchain>=1.0,<2" "pydantic>=2.7,<3"
```

Chạy bốn demo:

```powershell
python .\BTVN03\flight_agent.py
python .\BTVN03\flight_agent_plan_then_execute.py
python .\BTVN03\flight_agent_hybrid.py
python .\BTVN03\flight_agent_failure_mode.py
```

| File | Mẫu agent / mục tiêu | Kịch bản chính |
| --- | --- | --- |
| `flight_agent.py` | ReAct | Chọn `1` để đặt VN122 hợp lệ; chọn `2` để xem harness chặn VJ604 và handoff. |
| `flight_agent_plan_then_execute.py` | Plan-then-Execute | Lập kế hoạch, chờ người dùng duyệt, rồi chạy tuần tự các bước. |
| `flight_agent_hybrid.py` | Mẫu Lai | Lập kế hoạch trước; nếu kế hoạch bị chặn, ReAct tìm phương án phù hợp hoặc handoff. |
| `flight_agent_failure_mode.py` | Thí nghiệm lỗi | Minh họa loop, tool hallucination, goal drift và state corruption khi bật/tắt harness. |

Harness của BTVN03 kiểm soát bốn điểm: ràng buộc được lưu dưới dạng dữ liệu, kiểm tra quyền trước khi gọi tool, xác nhận hoàn thành bằng code và bàn giao cho người dùng khi không thể hoàn tất đúng điều kiện. Báo cáo chi tiết nằm tại [BaoCao_BTVN03_Agent_Dat_Ve_May_Bay.pdf](./BTVN03/BaoCao_BTVN03_Agent_Dat_Ve_May_Bay.pdf).

### BTTL — Agent Tools & Skills Lab

BTTL là **Bài tập tại lớp** gồm năm stage tăng dần khả năng của LangChain agent: chat, thao tác file, dùng skill, chạy Bash và skill có script kiểm tra CSV.

BTTL yêu cầu Python 3.11 trở lên, [uv](https://docs.astral.sh/uv/) và API key của provider OpenAI hoặc endpoint tương thích OpenAI Chat Completions có hỗ trợ native tool calling.

Từ thư mục gốc repository, cài môi trường và phụ thuộc chung cho cả năm stage:

```powershell
cd .\BTTL\agent-tools-skills-lab\agent-tools-skills-lab
uv sync --all-packages --locked
```

Vào stage muốn chạy, ví dụ Stage 02, rồi tạo file cấu hình cục bộ:

```powershell
cd stage-02-skills
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Mở `.env` và điền cấu hình của provider:

```dotenv
OPENAI_API_KEY=your_provider_api_key
MODEL_NAME=your_tool_calling_model
OPENAI_BASE_URL=https://your-provider.example/v1
```

`OPENAI_BASE_URL` là tùy chọn. Endpoint dùng biến này phải hỗ trợ `tools`, `tool_calls` và message role `tool`.

Chạy ứng dụng và test từ thư mục của stage:

```powershell
uv run streamlit run app.py
uv run pytest
```

Stage 01–04 có thể khôi phục dữ liệu mẫu bằng `uv run python reset_workspace.py`; test dùng mock model nên không cần API key. Riêng `stage-03-bash` và `stage-04-script-skill` cần môi trường POSIX có Bash—trên Windows, hãy chạy bằng WSL2.

Xem [README của BTTL](./BTTL/agent-tools-skills-lab/agent-tools-skills-lab/README.md) để biết mục tiêu, tools, skills và lệnh reset của từng stage.

> Trên macOS/Linux, kích hoạt môi trường bằng `source .venv/bin/activate`.

---

## Bảo mật và quy ước

- Không đưa API key, token, mật khẩu hoặc thông tin xác thực vào source code, tài liệu hay commit.
- Bài nào cần thông tin nhạy cảm thì lưu cục bộ trong `.env` và đưa mẫu an toàn vào `.env.example`; dùng `.gitignore` để loại trừ `.env`, `.venv` và cache.
- BTVN03 không sử dụng bí mật hay dịch vụ bên ngoài, vì vậy không cần tạo `.env`.
- Nếu một API key đã bị lộ, hãy thu hồi hoặc xoay key tại nhà cung cấp ngay.

## Tài liệu tham khảo

- [LangChain documentation](https://docs.langchain.com/oss/python/langchain/overview)
- [LangGraph documentation](https://docs.langchain.com/oss/python/langgraph/overview)
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
