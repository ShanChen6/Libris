# Pipeline xử lý văn bản pháp luật

## Task 2.1 – Hierarchical Chunking

```bash
cd libris-ai
uv run python -m app.pipeline chunk --dry-run                  # chỉ xem báo cáo chất lượng
uv run python -m app.pipeline chunk                            # cắt toàn bộ văn bản -> legal_chunks
uv run python -m app.pipeline chunk --document 168/2024/NĐ-CP  # cắt lại một văn bản
```

Đầu vào là `legal_documents.full_text` (đã nạp bằng `python -m crawler load-db`). Chạy lại lệnh sẽ
thay thế toàn bộ chunk của văn bản đó.

### Nhận diện cấu trúc

Mỗi đơn vị cấu trúc bắt đầu một dòng (bộ làm sạch của crawler đã đảm bảo điều này). Parser
(`chunking.py`) nhận diện **Phần → Chương → Mục → Điều → Khoản → Điểm**, có tính đến lỗi của bản
OCR:

| Tình huống | Cách xử lý |
|---|---|
| Số Chương OCR hỏng ("Chương HI", "Chương ]", "Chương") | Đánh số Chương theo thứ tự xuất hiện; chỉ dùng số đọc được khi hợp lệ và khớp thứ tự |
| "Điều I." / "À Điều 2." / "“Điều 80." (rác OCR) | Quy đổi `I`/`l` → `1`, chấp nhận ký tự rác ở đầu dòng; ngoặc kép chỉ được chấp nhận khi đúng số Điều kế tiếp |
| "Chương II và Chương IV Nghị định này…", "Điều 5 của Luật này…" | Là câu văn, không phải tiêu đề |
| “Điều 17. …” trong luật sửa đổi | Là nội dung trích dẫn của Điều đang sửa đổi |
| Số Điều/Khoản/Điểm phải tăng dần | Tiêu đề nhảy số bất thường bị coi là nội dung; số Điều bị thiếu được báo cáo |
| Khối chữ ký, "Nơi nhận" (kể cả khi OCR dồn vào một dòng) | Kết thúc phần chính, bị bỏ qua |
| Phụ lục / Mẫu biểu (có thể chứa "Điều 1." của mẫu quyết định) | Thành các đoạn riêng `part = 'Phụ lục'` |

### Quy tắc cắt đoạn (`--max-chars`, mặc định 1800 ký tự)

1. **Căn cứ ban hành** → một đoạn riêng.
2. **Điều ngắn** → cả Điều là một đoạn.
3. **Điều dài** → mỗi Khoản một đoạn; dòng tiêu đề Điều gộp vào Khoản đầu tiên.
4. **Khoản dài** → nhóm các Điểm liên tiếp. **Câu dẫn của Khoản** (VD: *"Phạt tiền từ 200.000
   đồng đến 400.000 đồng đối với … sau đây:"*) được đưa vào tiền tố ngữ cảnh của mọi nhóm, để đoạn
   chứa Điểm h vẫn mang theo mức phạt.
5. **Đoạn văn vượt giới hạn** (VD: bảng phụ lục bị OCR thành một dòng) → tách theo ranh giới câu.

Mỗi đoạn có:

- `context_prefix`: `[Văn bản: Nghị định 168/2024/NĐ-CP | Chương II: … | Mục 1: … | Điều 7: … | Khoản 1: 1. Phạt tiền từ 200.000 đồng …]`
- `article`, `clause`, `point` (VD: `Điều 7`, `Khoản 1`, `Điểm h–k`): dùng để dựng thẻ trích dẫn
  `[Điều 7, Khoản 1 - 168/2024/NĐ-CP]` (Task 3.4)
- `char_start`/`char_end`: `content == full_text[char_start:char_end]`, dùng để bôi vàng đoạn được
  dẫn (Task 4.3)

### Giới hạn

Với bản OCR, một số tiêu đề Điều bị nhận dạng hỏng tới mức không khôi phục được (VD: tên Mục dính
liền tiêu đề Điều trên cùng một dòng). Nội dung của Điều đó khi ấy nằm trong đoạn của Điều liền
trước, nên trích dẫn có thể lệch một Điều. Danh sách Điều bị thiếu hiện trong báo cáo `chunk`. Các
văn bản này đều có `needs_review = true`.

## Task 2.2 – Embedding & chỉ mục tìm kiếm

```bash
cd libris-ai
uv run python -m app.pipeline embed           # sinh embedding cho các đoạn chưa có
docker compose run --rm migrate               # (ở gốc repo) tạo chỉ mục HNSW + GIN
uv run python -m app.pipeline search "Đi xe máy không có gương chiếu hậu bên trái có bị phạt không?"
```

- **Mô hình**: `BAAI/bge-m3` (dense, 1024 chiều, đa ngôn ngữ, hỗ trợ tiếng Việt). Lần đầu chạy sẽ
  tải khoảng 2,3 GB về `~/.cache/huggingface`. Cấu hình qua `EMBEDDING_*` trong `.env`.
- **Văn bản được nhúng** là `context_prefix + "\n" + content`, để vector mang cả ngữ cảnh "văn bản
  nào, Chương/Điều nào".
- Vector được **chuẩn hóa L2**, nên tìm kiếm dùng khoảng cách cosine (`<=>`).
- `embed` chỉ xử lý các đoạn có `embedding IS NULL` và commit theo từng lô (`--batch-size`). Bị
  ngắt thì chạy lại để làm tiếp. Dùng `--force` để sinh lại toàn bộ, VD khi đổi mô hình.
- `token_count` lưu số token thực của từng đoạn. Lệnh báo số đoạn vượt `EMBEDDING_MAX_SEQ_LENGTH`
  (mặc định 1024 token, phần vượt bị mô hình cắt bỏ).
- **PyTorch bản CPU** được lấy từ index `download.pytorch.org/whl/cpu` (xem `pyproject.toml`). Máy
  có GPU: đổi index sang bản CUDA và đặt `EMBEDDING_DEVICE=cuda`.

**Chỉ mục** (`db/migrations/20261123000005_search_indexes.sql`):

| Cột | Chỉ mục | Dùng cho |
|---|---|---|
| `embedding` | HNSW `vector_cosine_ops` (m=16, ef_construction=64) | tìm kiếm ngữ nghĩa |
| `search_vector` | GIN | tìm kiếm từ khóa, số hiệu văn bản |

`search.py` cung cấp `semantic_search` và `keyword_search`, mặc định chỉ trả về văn bản `ACTIVE`/
`AMENDED`. Vì bộ lọc trạng thái áp dụng sau khi quét HNSW, truy vấn bật
`hnsw.iterative_scan = relaxed_order` (pgvector ≥ 0.8), để vẫn đủ k kết quả khi nhiều đoạn gần
nhất thuộc văn bản đã hết hiệu lực. Task 3.1 sẽ hợp nhất hai luồng này bằng RRF.
