# Challenge C — Cache-Aware Model Router

Mô phỏng này chọn chiến lược có **expected total cost** thấp nhất cho một AI Agent Harness đang giữ 50.000 token context. Đây là công cụ minh họa có thể chạy local, không gọi LLM/API và chỉ dùng Python standard library.

## Chạy nhanh

Yêu cầu Python 3.10+.

```powershell
cd 'D:\BTVN-Agentic-AI\Challenge C'
python cache_aware_router.py demo
python -m unittest discover -s tests -v
```

Lệnh hữu ích:

```powershell
python cache_aware_router.py at-time --minutes 7
python cache_aware_router.py probability --return-probability 0.6 --horizon 10
python cache_aware_router.py sensitivity
```

## Kịch bản demo khi trình bày

Thời lượng gợi ý: 5–7 phút. Mở PowerShell ngay trong thư mục `Challenge C` và chạy theo đúng thứ tự bên dưới. Mỗi lệnh chỉ in một mô phỏng, không gọi API và không tạo dữ liệu lớn.

### 1. Mở đầu — bài toán (30 giây)

Nói: *"Agent đang có 50.000 token context trên Model A. Tôi không chọn model chỉ theo giá input; tôi tính tổng chi phí gồm cached input, keep-alive, compaction và retry. Router sẽ chọn tổng chi phí kỳ vọng thấp nhất."*

Nhắc nhanh bảng giá: A có input/output đắt hơn B, nhưng A đang có cache warm nên cached prefix của A chỉ $0.50/1M token.

### 2. Chứng minh baseline (45 giây)

```powershell
python -m unittest discover -s tests -v
```

Nói: *"Test xác nhận hai con số của slide: Warm A cache hit là $0.055; Switch B cold là $0.057. Chênh $0.002 cho thấy đổi sang model có giá input rẻ hơn chưa chắc rẻ hơn nếu ta bỏ cache."*

Nếu thầy hỏi phép tính, giải thích:

- Warm A: `50.000 × 0.50/1M + 2.000 × 5/1M + 1.000 × 20/1M = $0.055`.
- Switch B: `(50.000 + 2.000) × 1/1M + 1.000 × 5/1M = $0.057`.

### 3. Scenario 1 — user quay lại sau 3 phút (1 phút)

```powershell
python cache_aware_router.py at-time --minutes 3
```

Đọc bảng theo thứ tự: `Request` là chi phí request khi user quay lại; `Maint/Compact` là chi phí đã phát sinh trước đó hoặc compaction; `Total` là số router dùng để quyết định.

Nói: *"TTL là 5 phút, nên sau 3 phút cache A vẫn còn warm và chưa cần keep-alive. Warm A có total $0.055, thấp hơn Switch B $0.057 và Compact $0.074, nên router chọn Warm A."*

### 4. Scenario 2 — user quay lại sau 7 phút (1 phút)

```powershell
python cache_aware_router.py at-time --minutes 7
```

Nói: *"Để giữ cache qua phút thứ 7, hệ thống gửi một keep-alive ở phút thứ 4. Nó tốn $0.025 vì vẫn gửi 50.000 cached tokens. Vì vậy Warm A là $0.055 + $0.025 = $0.080. Switch B cold là $0.057, nên ở trường hợp này Switch B thắng. Điểm quan trọng là không được chỉ so sánh $0.055 với $0.057 mà bỏ chi phí duy trì cache."*

### 5. Scenario 3 — xác suất quay lại 60% trong 10 phút (1–2 phút)

```powershell
python cache_aware_router.py probability --return-probability 0.6 --horizon 10
```

Nói: *"User chỉ quay lại với xác suất 60%, và nếu quay lại thì thời điểm được giả định uniform từ 0 đến 10 phút. Warm A phải trả keep-alive ngay cả khi 40% user không quay lại. Expected maintenance là $0.012; tổng expected cost của Warm A là $0.045. Switch B chỉ trả khi request thực sự xảy ra, nên $0.057 × 0.6 = $0.0342 và được chọn."*

Sau đó nhấn mạnh: *"Đây là lý do router tối ưu expected total cost, không tối ưu chi phí của một request riêng lẻ."*

### 6. Sensitivity / break-even (45 giây)

```powershell
python cache_aware_router.py sensitivity
```

Nói: *"Với các giả định mặc định trong horizon 10 phút, output cho thấy P=0% chọn Warm A do hòa chi phí tại $0, còn từ 1% trở lên Switch B rẻ nhất. Đây là break-even trong miền đã quét. Nếu thay đổi TTL, keep-alive interval, retry rate hoặc compacted context, hàm router sẽ tính lại thay vì dùng quyết định hard-code."*

### 7. Kết luận (20 giây)

Nói: *"Kết luận không phải luôn giữ cache hay luôn đổi model. Nếu user quay lại sớm, Warm A tận dụng cached prefix. Nếu chờ lâu hoặc xác suất quay lại không chắc chắn, chi phí keep-alive có thể làm Switch B tốt hơn. Compact chỉ hợp lý khi lợi ích context nhỏ ở các request sau bù được chi phí compaction ban đầu."*

## Bối cảnh và thuật ngữ

AI Agent Harness quản lý state, history, memory và các lần gọi model. Khi context lớn, quyết định giữa giữ **warm prompt cache**, compaction, hoặc đổi model phải tính tổng chi phí, không chỉ giá input niêm yết.

**Prompt caching** tái dùng phần prefix đã xử lý: token vẫn chiếm context window và vẫn bị tính phí `cached input` (rẻ hơn), nhưng không lưu câu trả lời. **Response caching** là lưu/trả lại kết quả cuối cùng; mô phỏng này không dùng response caching.

## Dữ liệu slide và giả định minh họa

| Parameter ($/1M tokens) | Model A | Model B |
|---|---:|---:|
| Input | 5.00 | 1.00 |
| Cached input | 0.50 | 0.10 |
| Output | 20.00 | 5.00 |

- Existing context: 50.000 tokens; new input: 2.000; output kỳ vọng: 1.000.
- Context sau compaction: 12.000 tokens.
- TTL = 5 phút; keep-alive mỗi 4 phút. Đây là giả định cấu hình được, **không** phải cam kết của provider.
- Một keep-alive gửi prefix cached 50.000 token Model A; mặc định không có input/output mới. Nếu thành công, nó làm mới TTL.
- Compaction xảy ra khi user quay lại, dùng Model B cold để đọc 50.000 token và sinh 1.000 token.
- Retry mặc định 0. Khi đặt `r`, expected request cost = base request cost × `(1 + r)` (mô hình tối đa một retry độc lập).
- Cache của Model A không chuyển được sang Model B.

## Công thức

Với giá theo $/1M: `cost = tokens × price / 1_000_000`.

`request = cached_tokens×cached_price + uncached_tokens×input_price + output_tokens×output_price`.

- **Warm A** = keep-alive trước khi return + request A dùng cached prefix (chỉ hợp lệ nếu TTL chưa hết hoặc keep-alive đã chạy đúng hạn).
- **Cold & Compact** = cold compaction B + request sau context 12.000 token trên A hoặc B; router chọn biến thể compact rẻ nhất.
- **Switch B** = toàn bộ 50.000 context + new input được tính cold trên B; không dùng cache A.

## Kết quả mặc định

Baseline được test tự động: Warm A cache-hit = **$0.055**, Switch B cold = **$0.057**.

| Scenario | Warm A | Cold & Compact (B) | Switch B | Khuyến nghị |
|---|---:|---:|---:|---|
| Return sau 3 phút | $0.055 | $0.074 | $0.057 | Warm A |
| Return sau 7 phút | $0.080 | $0.074 | $0.057 | Switch B |
| P(return ≤10m)=60%, uniform nếu return | $0.045 | $0.044 | $0.034 | Switch B |

Ở scenario xác suất, Warm A phải trả keep-alive trước cả khi user không quay lại. Kỳ vọng số keep-alive là `0.6×P(T>4|return)+0.6×P(T>8|return)=0.48`; chi phí maintenance là $0.012. Compact/Switch chỉ có chi phí khi có request.

## Sensitivity và break-even

`sensitivity` quét return probability từ 0–100% với horizon, TTL, interval, retry và context compact đang cấu hình. Nó in ra đoạn chính sách tối ưu và ngưỡng đổi chiến lược; nếu không có thay đổi sẽ in đúng `No break-even point in the evaluated range`.

Ví dụ cấu hình mặc định 10 phút: Switch B thường thắng ở xác suất dương vì Warm A có maintenance cố định. Thay đổi TTL/interval, keep-alive payload, retry, context compact hoặc giá qua Python API sẽ làm router tính lại, không hard-code lựa chọn.

## Giới hạn

TTL/refresh semantics thực tế khác theo provider; quality, latency, cache eviction, tokenization và retry correlation không được suy diễn ở đây. Bài toán này tối ưu chi phí; nếu cần ràng buộc quality/latency, hãy lọc các chiến lược không đạt ràng buộc trước khi gọi router.
