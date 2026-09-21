# Agentic AI Issue Triage
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/Google_Gemini-API-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/gemini-api/docs)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.40+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![tiktoken](https://img.shields.io/badge/tiktoken-Tokenization-111111?style=for-the-badge&logo=openai&logoColor=white)](https://github.com/openai/tiktoken)

Các demo Python nhỏ, theo từng bước, để xây dựng quy trình phân loại software issue với Gemini: gọi model cơ bản, đo token, structured output, function calling có kiểm soát và giao diện Streamlit.

## Công nghệ sử dụng

| Công nghệ | Vai trò |
| --- | --- |
| Python | Ngôn ngữ chính cho toàn bộ demo |
| Google Gen AI SDK / Gemini | Phân loại issue, structured output và function calling |
| Streamlit | Giao diện web cho demo triage |
| Pydantic | Schema hóa kết quả structured output |
| tiktoken | So sánh số token giữa tiếng Anh và tiếng Việt |
| python-dotenv | Nạp cấu hình cục bộ từ `.env` |

## Bắt đầu nhanh

Yêu cầu: Python 3.10 trở lên và Google AI Studio API key.

```powershell
git clone https://github.com/BinCry/BTVN-Agentic-AI.git
cd BTVN-Agentic-AI\"Demo Issue Triage\"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
```

Mở file `.env` vừa tạo và điền key của riêng bạn:

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

Trên macOS/Linux, kích hoạt virtual environment bằng `source .venv/bin/activate` và sao chép file bằng `cp .env.example .env`.

## Chạy demo

Tất cả lệnh dưới đây được chạy bên trong thư mục `Demo Issue Triage`.

| Demo | Lệnh | Nội dung |
| --- | --- | --- |
| 00 | `python 00_minimal_triage.py` | Gửi một issue đến Gemini và in câu trả lời tự do |
| 01 | `python 01_measure_tokens.py` | So sánh token tiếng Anh và tiếng Việt với các tokenizer |
| 02 | `python 02_structured_output.py` | So sánh JSON bằng prompt với structured output theo Pydantic schema |
| 03 | `python 03_function_calling.py` | Function calling do ứng dụng kiểm soát và xác thực |
| 04 | `streamlit run 04_streamlit_triage.py` | Giao diện Streamlit hiển thị triage và tool trace |

Bạn có thể thay nội dung issue ở các demo CLI:

```powershell
python 03_function_calling.py --issue "Thanh toán Visa trả HTTP 500 từ 14:30"
```

## Function-calling flow

Demo 03 và 04 chỉ cho phép model yêu cầu `get_component_owner` cho ba component đã được ứng dụng phê duyệt: `payment`, `identity` và `search`. Ứng dụng xác thực tên tool, tham số và component trước khi thực thi; sau đó mới gửi kết quả về cho Gemini để tạo câu trả lời cuối cùng.

## Cấu trúc project

```text
Demo Issue Triage/
├── 00_minimal_triage.py       # Gemini cơ bản
├── 01_measure_tokens.py       # Đo token
├── 02_structured_output.py    # Structured output
├── 03_function_calling.py     # Function calling qua CLI
├── 04_streamlit_triage.py     # Function calling qua Streamlit
├── demo_common.py             # Cấu hình Gemini và biến môi trường dùng chung
├── triage_workflow.py         # Luồng triage và validation tool call
├── .env.example               # Mẫu cấu hình an toàn
└── requirements.txt
```

## Bảo mật API key

- Không đưa `GEMINI_API_KEY` thật vào mã nguồn, README, issue hoặc commit.
- Chỉ lưu key trong `Demo Issue Triage/.env` trên máy cục bộ.
- `.env`, virtual environment và cache đã được khai báo trong `.gitignore`.
- Nếu key từng bị lộ, hãy thu hồi hoặc xoay key ngay trong Google AI Studio.

## Đóng góp

Tạo branch riêng cho thay đổi, chạy demo liên quan và không commit file `.env` trước khi mở pull request.

## License

Repository hiện chưa có file license. Hãy liên hệ chủ repository trước khi tái sử dụng ngoài mục đích học tập.
