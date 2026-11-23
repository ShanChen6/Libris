# Truy xuất (Task 3.1, 3.2)

```bash
cd libris-ai
uv run python -m app.pipeline search "Đi xe máy không có gương chiếu hậu bên trái có bị phạt không?"
uv run uvicorn app.main:app --port 8000   # POST /search, xem /docs
```

```http
POST /search
{"query": "So sánh mức phạt vượt đèn đỏ cũ và mới", "top_k": 20}
```

Tham số tùy chọn: `include_expired` (bật/tắt văn bản hết hiệu lực, ghi đè Router), `as_of`
(`YYYY-MM-DD`: chỉ lấy văn bản có hiệu lực tại ngày đó), `weights` (`vector`, `keyword`,
`referenced`, `candidates`). Mỗi kết quả có `citation` (`[Điều 7, Khoản 2 - 168/2024/NĐ-CP]`),
trạng thái hiệu lực, `replaced_by` (văn bản thay thế, nếu đã hết hiệu lực), vị trí
`char_start`/`char_end`, và thứ hạng ở từng luồng (`vec_rank`, `kw_rank`, `ref_rank`) để giải thích
vì sao đoạn đó được chọn.

## Hybrid Search với RRF (`hybrid.py`)

Cả ba danh sách xếp hạng và bước hợp nhất nằm trong **một câu SQL** (các CTE `vec`, `kw`, `ref`,
`fused`):

```
RRF(đoạn) = w_vec/(60 + rank_vec) + w_kw/(60 + rank_kw) + w_ref/(60 + rank_ref)
```

| Luồng | Cách xếp hạng | Bắt được gì |
|---|---|---|
| `vec` | cosine của embedding bge-m3 (HNSW) | ý định câu hỏi đời thường |
| `kw` | `ts_rank_cd` trên `search_vector` (GIN), đã bỏ hư từ ("có", "không", "bị"…) | số hiệu văn bản, thuật ngữ pháp lý |
| `ref` | cosine, chỉ trong văn bản được nêu đích danh | ưu tiên văn bản người dùng hỏi tới |

RRF chỉ dùng **thứ hạng**, không dùng điểm gốc, nên không cần chuẩn hóa thang điểm giữa cosine và
`ts_rank`. Một đoạn đứng đầu cả hai luồng có điểm `2/61 ≈ 0,0328`. Trọng số và số ứng viên mỗi luồng
(`candidates`, mặc định 50) là tham số để tinh chỉnh bằng RAGAS (Task 5.2). Top 20 kết quả sẽ được
đưa qua reranker (Task 3.3).

## Lọc hiệu lực & Query Router (`router.py`)

| Câu hỏi | Chế độ | Phạm vi văn bản |
|---|---|---|
| Mặc định | `current` | `ACTIVE`, `AMENDED` (không tư vấn theo luật cũ) |
| "so sánh", "khác gì", "trước đây", "luật cũ", "còn hiệu lực không"… | `compare` | thêm `EXPIRED` |
| "vào năm 2019", "tại thời điểm ngày 15/6/2024", "trước ngày 1/1/2025" | `point_in_time` | văn bản có hiệu lực trong khoảng đó: `effective_date ≤ cuối khoảng` và (`expiry_date` trống hoặc `> đầu khoảng`) |
| Nêu số hiệu "100/2019/NĐ-CP" hoặc tên kèm năm "Luật Đất đai 2013" | (giữ chế độ) | văn bản đó luôn được tìm, kể cả khi đã hết hiệu lực, và có thêm luồng `ref` |
| "sắp có hiệu lực", "sẽ có hiệu lực" | (giữ chế độ) | thêm `PENDING` |

Năm nằm trong số hiệu ("168/**2024**/NĐ-CP") hay trong tên văn bản ("Luật Đất đai **2013**") không
bị hiểu nhầm là mốc thời gian. Tên kèm năm được tra ra số hiệu trong `legal_documents` (cùng loại
văn bản, cùng năm, tên khớp). Lý do của từng quyết định nằm trong `plan.reasons`, có thể hiển thị
cho người dùng.

Router hiện dựa trên luật (regex chịu lỗi dấu), nên nhanh, giải thích được và không tốn chi phí gọi
LLM. Khi bộ Golden Dataset (Task 5.1) cho thấy có nhiều câu hỏi bị phân loại sai, có thể thay
bằng bộ phân loại LLM, vẫn giữ nguyên giao diện `route(query) -> RetrievalPlan`.
