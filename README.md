# BTVN Agentic AI — Kho lưu trữ bài tập thực hành

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/Gemini-Google_Gen_AI-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/gemini-api/docs)
[![License](https://img.shields.io/badge/License-Educational-green?style=for-the-badge)](https://github.com/BinCry/BTVN-Agentic-AI)

Repository tổng hợp mã nguồn, bài tập về nhà (BTVN) và các dự án thực hành qua các buổi trong khóa học **Agentic AI**.

---

## 📂 Danh sách bài tập

| Buổi | Thư mục | Chủ đề | Công nghệ / Tính năng chính |
| :--- | :--- | :--- | :--- |
| **Buổi 02** | [`BTVN02/`](./BTVN02/) | **Agentic AI Issue Triage** | • LLM Minimal Call<br>• Đo lường Token (tiktoken)<br>• Structured Output với Pydantic<br>• Controlled Function Calling<br>• Giao diện Web Streamlit |
| **Buổi 03** | `BTVN03/` *(Sắp tới)* | *Đang cập nhật...* | *Đang cập nhật...* |

---

## 🏗️ Cấu trúc Repository

```text
BTVN-Agentic-AI/
├── BTVN02/                         # Bài tập buổi 2: Issue Triage with Gemini
│   ├── 00_minimal_triage.py        # Demo 00: Gọi Gemini cơ bản
│   ├── 01_measure_tokens.py        # Demo 01: Đo token tiếng Anh/Việt
│   ├── 02_structured_output.py     # Demo 02: Structured output với Pydantic
│   ├── 03_function_calling.py      # Demo 03: Function calling có kiểm soát
│   ├── 04_streamlit_triage.py      # Demo 04: Giao diện web Streamlit
│   ├── demo_common.py              # Cấu hình Gemini & biến môi trường
│   ├── triage_workflow.py          # Luồng triage và validation tool call
│   ├── demo-guide.html             # Hướng dẫn chi tiết định dạng HTML
│   ├── requirements.txt            # Thư viện phụ thuộc cho BTVN02
│   ├── README.md                   # Hướng dẫn chi tiết cho BTVN02
│   └── docs/                       # Tài liệu & nhật ký phát triển
├── README.md                       # Giới thiệu tổng quan repository
└── .gitignore                      # Cấu hình bỏ qua các file nhạy cảm và cache
```

---

## 🚀 Hướng dẫn bắt đầu chung

Mỗi bài tập được thiết kế độc lập theo từng thư mục (ví dụ: `BTVN02/`). Để làm việc với một bài tập cụ thể:

### 1. Clone Repository
```powershell
git clone https://github.com/BinCry/BTVN-Agentic-AI.git
cd BTVN-Agentic-AI
```

### 2. Di chuyển vào thư mục bài tập cần chạy
```powershell
cd BTVN02
```

### 3. Thiết lập môi trường Python & Cài đặt dependencies
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

*(Trên macOS / Linux: sử dụng `source .venv/bin/activate`)*

### 4. Cấu hình biến môi trường
Tạo file `.env` từ file mẫu `.env.example` và điền API key của bạn:
```powershell
Copy-Item .env.example .env
```

Xem hướng dẫn chi tiết về cách chạy từng demo và tính năng trong `README.md` của từng thư mục bài tập (ví dụ: [`BTVN02/README.md`](./BTVN02/README.md)).

---

## 🔒 Quy ước bảo mật (Security Best Practices)

- **Tuyệt đối không đưa API Key thật** vào mã nguồn, README hay commit lên GitHub.
- Tất cả API Key đều được nạp thông qua file `.env` cục bộ. File `.gitignore` ở root và từng thư mục đã được cấu hình để chặn upload `.env`, virtual environment (`.venv`) và cache.
- Khi chia sẻ mã nguồn hoặc nộp bài, chỉ chia sẻ mã nguồn sạch, không bao gồm thông tin xác thực hay quota cá nhân.
