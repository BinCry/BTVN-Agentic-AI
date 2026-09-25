# BTVN03 — Controlled Flight-Booking Agents

## Mục tiêu

Xây dựng môi trường đặt vé máy bay hoàn toàn mô phỏng để so sánh ba kiến trúc Agent: ReAct, Plan-then-Execute và Hybrid. Trọng tâm là **harness kiểm soát**: model chỉ đề xuất tool call; code kiểm tra ràng buộc, quyền, thực thi, ghi observation và quyết định dừng.

Không có API hãng bay, thanh toán hoặc cơ sở dữ liệu thật. Toàn bộ dữ liệu được reset trước mỗi lần chạy nên benchmark công bằng và lặp lại được.

## Kiến trúc tổng thể

```text
Agent strategy (ReAct | Plan | Hybrid)
              │ Action(tool, args)
              ▼
ConstraintHarness → PermissionHarness → mock tool
              │                         │
              └────── structured observation
                              │
                              ▼
CompletionHarness → LoopDetector → BudgetGuard / Stall check
                              │
                  continue | success | handoff | failure
```

File nộp chính là `btvn3_flight_agent.py`; mười section comment trong file lần lượt là config, models, mock DB/tools, harness, ba agent, evaluation và CLI.

## Dữ liệu, tools và ràng buộc

`BookingConstraints` là Pydantic model chứa route, ngày bay, giờ muộn nhất, giá trần, seat preference, refundable-only và auto-pay limit. Ràng buộc không được giấu trong prompt.

`MockFlightDB` có 8 chuyến, trong đó có chuyến hợp lệ, hết ghế, quá giá, sau giờ giới hạn và không hoàn. Năm mock tools đều trả JSON có schema:

| Tool | Vai trò |
|---|---|
| `search_flights` | Read-only; trả danh sách chuyến theo route/date |
| `check_seat` | Read-only; trả available/full/timeout |
| `book_seat` | Side effect; giữ ghế và sinh booking code |
| `pay_booking` | High-risk side effect mô phỏng |
| `get_booking` | Read-only; xác minh booking sau thanh toán |

`CompletionHarness` chỉ trả thành công sau `get_booking`, khi DB xác nhận `confirmed`, `paid`, đúng route/date/time và không vượt giá trần. `PermissionHarness` chạy trước `pay_booking`: nếu giá vượt `auto_pay_limit` hoặc vé không hoàn thì tạo `NEED_HUMAN`, không gọi mock payment.

## Ba kiến trúc

- **ReAct**: policy đề xuất một action, đọc observation rồi chọn action kế tiếp. Benchmark dùng policy deterministic để mỗi kiến trúc cùng điều kiện, không cần API key. `--model-mode langchain` dùng `langchain.agents.create_agent`; năm tool wrapper vẫn chỉ đi qua `ExecutionHarness`.
- **Plan-then-Execute**: planner tạo một `list[PlanStep]` đúng một lần. Executor không replan nếu candidate đã full, qua đó bộc lộ rủi ro kế hoạch lỗi thời.
- **Hybrid**: tạo plan, chạy `k=2` bước, rồi replan nếu check seat thất bại hoặc environment thay đổi. Mọi lần replan được đếm trong metrics.

## Scenarios

| ID | Tình huống | Mục đích |
|---|---|---|
| S1 | VN122 hợp lệ ngay | baseline |
| S2 | Candidate đầu tiên full | khả năng thích nghi |
| S3 | Không có chuyến đúng giá/giờ | graceful failure |
| S4 | Giá vượt auto-pay limit | permission + structured handoff |
| S5 | `check_seat(VN122)` timeout lặp lại | LoopDetector |
| S6 | VN122 chuyển full sau plan ban đầu | so sánh plan với hybrid |

## Benchmark thực tế

Đã chạy lệnh `python btvn3_flight_agent.py --benchmark --repeats 1`: 18 runs, gồm 3 pattern × 6 scenarios. Số liệu nguồn nằm trong `results.csv`; không hard-code trong chương trình.

| Pattern | Success | Model calls TB | Tool calls TB | Steps TB | Replans TB | Tổng violation |
|---|---:|---:|---:|---:|---:|---:|
| ReAct | 3/6 | 4.67 | 4.50 | 4.67 | 0.00 | 1 |
| Plan | 1/6 | 1.00 | 2.50 | 2.67 | 0.00 | 1 |
| Hybrid | 3/6 | 2.00 | 4.50 | 4.67 | 1.00 | 1 |

| Pattern | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---|---|---|---|---|---|
| ReAct | success | success | failure | need_human | loop | success |
| Plan | success | failure | failure | need_human | failure | failure |
| Hybrid | success | success | failure | need_human | loop | success |

Một violation ở mỗi pattern là PermissionHarness cố ý chặn payment S4; không có thanh toán mock nào được thực thi ở lần đó. Latency được ghi cho từng run nhưng chỉ phản ánh Python in-memory nên không dùng để kết luận hiệu năng LLM.

## Phân tích

ReAct đổi candidate sau mỗi observation nên thành công S2 và S6, nhưng cần nhiều model decisions hơn. Plan rẻ nhất về model calls và dễ duyệt trước, đổi lại không phục hồi khi dữ liệu thay đổi. Hybrid trả giá bằng replan và trace phức tạp hơn, nhưng khôi phục được candidate trong S2/S6. S5 cho thấy termination không phụ thuộc vào việc model tự dừng: retry cùng một tool/args lần thứ ba bị LoopDetector kết thúc.

Ví dụ S4 sau khi ghế `12A` của `VN122` đã được giữ:

```text
[04] MODEL -> pay_booking({"booking_code": "BOOK001"})
[04] NEED_APPROVAL -> {"status": "need_human", ...}
STOP -> need_human
```

Handoff schema nêu rõ `flight`, `seat`, `price`, booking code, side effect đã xảy ra, các attempts, blocker và câu hỏi “Approve payment of 1,850,000 VND for VN122?”.

## Chạy cục bộ trong BTVN03

Từ đúng thư mục `BTVN03`, môi trường ảo, pip cache và temporary files đều được đặt tại đây:

```powershell
New-Item -ItemType Directory -Force .tmp, .pip-cache
$env:TEMP = (Resolve-Path .tmp).Path
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = (Resolve-Path .pip-cache).Path
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe btvn3_flight_agent.py --self-test
.\.venv\Scripts\python.exe btvn3_flight_agent.py --pattern react --scenario S1
.\.venv\Scripts\python.exe btvn3_flight_agent.py --pattern plan --scenario S1
.\.venv\Scripts\python.exe btvn3_flight_agent.py --pattern hybrid --scenario S6
.\.venv\Scripts\python.exe btvn3_flight_agent.py --benchmark --repeats 1
```

Để dùng LLM thật cho ReAct, sao chép `.env.example` thành `.env`, điền `SE373_MODEL` và provider key qua environment; sau đó dùng `--model-mode langchain`. Không commit `.env`.

## Kết luận

Bài nộp có ba pattern dùng cùng DB/tools/harness, completion được code xác minh, effectful actions được permission kiểm tra trước khi chạy, structured handoff đầy đủ và benchmark reset state cho từng run. Điều này giữ ranh giới rõ ràng giữa model proposal và deterministic control plane của harness.
