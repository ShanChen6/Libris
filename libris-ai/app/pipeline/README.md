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
| Số Khoản OCR hỏng ("%, Phạt tiền..." thay cho "5. Phạt tiền...") | Nhận là Khoản kế tiếp khi dòng bắt đầu bằng 1–2 ký hiệu hay bị nhầm với chữ số, theo sau là chữ hoa, và Khoản trước đã kết thúc bằng dấu chấm (trước đây cả Khoản 5 Điều 6 NĐ 168/2024 bị gộp vào Khoản 4) |
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

### Hiệu đính dấu thanh sau OCR (`ocr_fix.py`)

Tesseract (vie) hay bỏ dấu thanh trên â/ê/ô: "đất" -> "đât" (4.400 lần trong kho), "điều" -> "điêu",
"cầm" -> "câm"... khiến tìm theo từ khóa trượt ("cầm điện thoại" không khớp "câm điện thoại") và văn
bản hiển thị khó đọc. `ocr_fix.py` sửa theo **ngữ cảnh hai âm tiết**, học từ 6 văn bản không qua OCR
của kho (~213.000 âm tiết):

- chỉ thay bằng âm tiết khác **dấu thanh** (giữ nguyên chữ cái, kể cả â/ê/ô/ư/ơ/đ): "dưỡng" không
  thể thành "đường";
- dạng mới phải hợp với **cả từ trước lẫn từ sau** (điểm = tích hai phía), dạng gốc chưa từng gặp
  trong ngữ cảnh đó; dấu câu không được tính là bằng chứng ("b) Tảo hôn" giữ nguyên);
- con số và độ dài văn bản không đổi, nên vị trí trích dẫn (`char_start`/`char_end`) vẫn đúng.

Kết quả: ~29.000 chỗ sửa trên 12 văn bản OCR; lấy ngẫu nhiên 40 chỗ để kiểm tra tay: cả 40 đúng.

Ngoài dấu thanh, `fix_ocr` sửa thêm ba loại lỗi mặt chữ (độ dài văn bản vẫn không đổi):

| Bước | Lỗi | Cách sửa | Số chỗ |
|---|---|---|---|
| `fix_confusions` | ký tự dễ nhầm trong từ: "1y hôn", "g1ao", "ø1a" | thay 1→l/i/t, 0→o/ô/ơ, 8→g, ø→g, j→l/i...; dạng mới phải là âm tiết tiếng Việt (có nguyên âm, không phải số La Mã), có trong từ vựng của **cả kho** (kho sạch không có luật hôn nhân nên thiếu "ly hôn") và được ngữ cảnh xác nhận; bỏ qua số hiệu như "khoản 8a" | ~50 |
| `fix_point_labels` | nhãn Điểm đọc sai: "©)" "8)" "¡)" "1)" "])" | dựa vào thứ tự a, b, c, d, đ, e, g, h, i, k, l... của Điểm liền trước: nhãn sai được thay bằng chữ kế tiếp nếu là ký tự hay bị nhầm với chữ đó; "đ)" ngay sau "c)" chỉ thành "d)" khi Điểm sau là "đ)" hoặc "e)" | ~440 |
| `fix_clause_numbers` | số Khoản đọc sai và dính vào Khoản trước: "...mục đích khác. l6. Thành viên" | khi bằng đúng số Khoản kế tiếp trong Điều: sửa số và đưa xuống dòng (thay khoảng trắng đứng trước) | 1 |

Nhãn Điểm đúng giúp cắt đoạn ghi đúng "Điểm g" thay vì gộp sai, và giúp bộ kiểm tra trích dẫn
(`generation/verify.py`) tìm đúng dòng của Điểm được dẫn. Không có bản văn bản gốc dạng chữ: từ môi
trường chạy, vbpl.vn trả 403 và congbao.chinhphu.vn ngắt kết nối; vanban.chinhphu.vn chỉ có PDF
quét. Khi lấy được bản chữ gốc (hoặc OCR lại bằng mô hình thị giác), nên thay hẳn văn bản OCR.

Chạy cho kho có sẵn (sau đó tự cắt đoạn và sinh embedding lại):

```bash
uv run python -m app.pipeline ocrfix --dry-run   # chỉ đếm
uv run python -m app.pipeline ocrfix
```

Văn bản Admin tải lên có trang OCR được hiệu đính tự động khi nạp. Văn bản vẫn giữ `needs_review`
vì lỗi khác (số, ký hiệu rác) không sửa được bằng cách này. Cắt lại đoạn làm trích dẫn trong lịch
sử chat cũ mất liên kết tới đoạn luật (`chunk_id` thành NULL); nhãn và nội dung trích dẫn vẫn giữ.

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
