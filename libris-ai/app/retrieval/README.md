# Truy xuất (Task 3.1, 3.2, 3.3)

```
câu hỏi → Query Router → mở rộng thuật ngữ → embedding → Hybrid Search (RRF) → Cross-encoder rerank → Top 5
```

Toàn bộ luồng nằm trong `service.retrieve()`, được API, CLI, script đánh giá và bước sinh câu
trả lời (Task 3.4) dùng chung.

```bash
cd libris-ai
uv run python -m app.pipeline search "Đi xe máy không có gương chiếu hậu bên trái có bị phạt không?"
uv run uvicorn app.main:app --port 8000   # POST /search, xem /docs
```

```http
POST /search
{"query": "So sánh mức phạt vượt đèn đỏ cũ và mới"}
```

Tham số tùy chọn: `rerank` (mặc định `true`), `top_n` (mặc định 5), `candidates` (số ứng viên
đưa vào reranker, mặc định `RERANK_CANDIDATES`), `include_expired` (bật/tắt văn bản hết hiệu lực, ghi đè Router), `as_of`
(`YYYY-MM-DD`: chỉ lấy văn bản có hiệu lực tại ngày đó), `weights` (`vector`, `keyword`,
`referenced`, `candidates`). Mỗi kết quả có `citation` (`[Điều 7, Khoản 2 - 168/2024/NĐ-CP]`),
trạng thái hiệu lực, `replaced_by` (văn bản thay thế, nếu đã hết hiệu lực), vị trí
`char_start`/`char_end`, và thứ hạng ở từng luồng (`vec_rank`, `kw_rank`, `ref_rank`) để giải thích
vì sao đoạn đó được chọn. Khi rerank, mỗi kết quả có thêm `rerank_score` (độ liên quan 0–1) và
`hybrid_rank` (thứ hạng trước khi rerank).

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
`ts_rank`. Luồng `kw` tìm theo **cụm hai âm tiết liền nhau** (`('đèn' <-> 'tín') | ('tín' <-> 'hiệu')`):
OR từng âm tiết khớp hàng nghìn đoạn. Trọng số (chọn bằng Golden Dataset – xem
[eval/README.md](../../eval/README.md)): vector 1, từ khóa **1** khi có reranker (CP@5 0,798 so với
0,789 ở 0,25); **0,25** khi không có reranker (0,661 so với 0,540). Một đoạn đứng đầu cả hai luồng có
điểm `2/61 ≈ 0,0328`.
Số ứng viên mỗi luồng là `candidates` (mặc định 50); Top `RERANK_CANDIDATES` kết quả được đưa qua
reranker (Task 3.3).

### Câu hỏi nhiều ý (`decompose.py`)

Một lượt truy xuất cho câu nhiều ý thường chỉ lấy được căn cứ cho một ý. Hai dạng được tách thành câu
hỏi con, mỗi câu truy xuất và rerank riêng, mỗi ý giữ tối thiểu ⌊Top N / số ý⌋ chỗ:

- "Đi xe máy **vừa** không đội mũ bảo hiểm **vừa** vượt đèn đỏ thì bị phạt..." -> một câu cho mỗi
  hành vi;
- nhiều vế hỏi: "Công ty bắt tôi thử việc 90 ngày... Như vậy **có đúng luật không**, công ty **bị phạt
  thế nào**?" -> mỗi vế hỏi kèm câu bối cảnh.

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

### Lọc ở cấp Điều/Khoản

Trạng thái `AMENDED` ở cấp văn bản là chưa đủ. VD: NĐ 168/2024 **bãi bỏ Điều 5–11, 16–22, 25–27,
29–38…** của NĐ 100/2019 (phần đường bộ), trong khi phần đường sắt của NĐ 100/2019 vẫn còn hiệu lực.
Nếu chỉ lọc theo văn bản, chatbot sẽ trả lời theo mức phạt cũ.

Bảng `superseded_provisions` (do `crawler normalize` trích từ các danh sách "Bãi bỏ Điều…, khoản…
Điều…" và "Sửa đổi, bổ sung khoản … Điều … như sau") liệt kê các Điều/Khoản không còn hiệu lực:

| Chế độ | Đoạn thuộc Điều/Khoản bị bãi bỏ hoặc thay nội dung |
|---|---|
| `current` | bị loại nếu `effective_date ≤ hôm nay` |
| `point_in_time` | bị loại nếu bị bãi bỏ trước đầu khoảng thời gian hỏi |
| `compare` | được giữ lại để đối chiếu |

Mỗi kết quả có `superseded_by` (VD `["repealed:168/2024/NĐ-CP"]`) để LLM cảnh báo khi trích dẫn.
Việc bãi bỏ ở cấp **Điểm** bị bỏ qua, vì đoạn chứa Điểm đó vẫn còn nội dung khác đang có hiệu lực.

### Mở rộng truy vấn (`expansion.py`)

Người dùng hỏi "vượt đèn đỏ", "sổ đỏ", "bằng lái", "nghỉ đẻ"…, còn văn bản viết "không chấp hành
hiệu lệnh của đèn tín hiệu giao thông", "giấy chứng nhận quyền sử dụng đất", "giấy phép lái xe",
"nghỉ thai sản". Thuật ngữ tương ứng được nối vào câu truy vấn trước khi tìm, ở cả hai luồng vector
và từ khóa. Router vẫn phân tích câu gốc.

### Đánh giá nhanh

```bash
uv run python eval/retrieval_smoke.py              # Hybrid Search
uv run python eval/retrieval_smoke.py --rerank     # + cross-encoder (cấu hình thật của hệ thống)
```

| Cấu hình | Recall@20 | Ghi chú |
|---|---|---|
| Hybrid RRF | 9/10 | trượt "vượt đèn đỏ" (khác cách diễn đạt) |
| + mở rộng truy vấn | 10/10 | |
| + lọc cấp Điều/Khoản | 10/10, MRR 0,53 | đoạn đúng lên hạng cao hơn vì bớt đoạn lỗi thời |

## Tái xếp hạng – Cross-encoder (`rerank.py`, Task 3.3)

Hybrid Search so khớp gần đúng (vector của câu hỏi và vector của đoạn được tính riêng). Cross-encoder
`BAAI/bge-reranker-v2-m3` đọc **đồng thời** câu hỏi và từng đoạn luật nên chấm mức độ liên quan
chính xác hơn nhiều. Đổi lại, mô hình chậm, nên chỉ chấm lại Top N ứng viên rồi giữ Top 5 cho LLM.

| Cấu hình (`eval/retrieval_smoke.py`) | Recall@1 | Recall@5 | MRR | Thời gian/câu (CPU 4 nhân) |
|---|---|---|---|---|
| Hybrid RRF (đã mở rộng + lọc cấp Điều) | 4/10 | 7/10 | 0,531 | 0,9 s |
| + rerank bằng **câu gốc**, 20 ứng viên | 7/10 | 9/10 | 0,767 | 15,4 s |
| + rerank bằng **câu đã mở rộng**, 20 ứng viên | 8/10 | **10/10** | 0,867 | 15,9 s |
| + rerank bằng câu đã mở rộng, **10 ứng viên** | 8/10 | **10/10** | **0,883** | **9,3 s** |

- Reranker nhận **câu đã mở rộng thuật ngữ**: "vượt đèn đỏ" khớp được với "không chấp hành hiệu
  lệnh của đèn tín hiệu giao thông" (từ hạng 11 lên hạng 3).
- `rerank_score` ∈ [0, 1]. Câu trả lời đúng thường đạt ≥ 0,85; đoạn không liên quan gần 0. Task 3.4
  sẽ dùng ngưỡng này để từ chối trả lời khi kho không có điều luật đủ liên quan.
- **Tốc độ trên CPU** khoảng 0,8 giây mỗi cặp (câu hỏi, đoạn). Mặc định 20 ứng viên theo roadmap; khi
  chạy CPU (VD Render/Railway, Task 6.1) nên đặt `RERANK_CANDIDATES=10`: nhanh gấp đôi, không giảm
  chất lượng trên bộ thử. Có GPU (`RERANKER_DEVICE=cuda`) thì 20 ứng viên chỉ mất dưới 1 giây.
- Đã thử lượng tử hóa int8 (`torch.ao.quantization.quantize_dynamic`) nhưng không tương thích với
  XLM-RoBERTa trên transformers 5 / torch 2.15. Hướng tăng tốc tiếp theo nếu cần: xuất ONNX (int8)
  hoặc dùng dịch vụ rerank có GPU.
