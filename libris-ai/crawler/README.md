# Crawler văn bản pháp luật (Task 1.2)

Thu thập văn bản quy phạm pháp luật từ **Hệ thống văn bản của Chính phủ**
([vanban.chinhphu.vn](https://vanban.chinhphu.vn)). Toàn văn lấy từ file đính kèm trên
`datafiles.chinhphu.vn`: PDF bản Công báo, hoặc `.doc`/`.docx` với các văn bản cũ.

## Cách chạy

```bash
cd libris-ai
uv sync
uv run python -m crawler crawl                 # crawl toàn bộ văn bản trong seeds.yaml
uv run python -m crawler fetch 211194 198540   # crawl theo docid
uv run python -m crawler list --org chinh-phu --type nghi-dinh --pages 2   # xem văn bản mới
```

Tùy chọn: `--force` (tải và xử lý lại), `--no-ocr`, `--delay 1.0` (số giây giữa 2 request tới
cùng một host), `--data-dir`.

Công cụ hệ thống: Tesseract kèm dữ liệu tiếng Việt (OCR cho PDF scan) và `catdoc` (đọc file
Word `.doc` cũ):

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-vie catdoc   # Ubuntu/Debian
brew install tesseract tesseract-lang catdoc                     # macOS
```

Nếu không có Tesseract, trang scan được ghi là `empty` và văn bản được gắn `needs_review: true`.

## Luồng xử lý

1. **Tra cứu `docid`**: với mỗi seed chưa có `source_id`, duyệt danh sách văn bản theo nhóm cơ
   quan và loại văn bản (50 văn bản mỗi trang, mới nhất trước; chuyển trang bằng ASP.NET
   postback). Dừng khi đã tìm đủ hoặc khi đã lùi quá năm ban hành của seed. Kết quả được cache
   trong `data/raw/vanban.chinhphu.vn/resolved.json`.
2. **Trang chi tiết**: lấy số hiệu, loại văn bản, cơ quan ban hành, người ký, trích yếu, ngày
   ban hành, **ngày có hiệu lực** và các file đính kèm.
3. **Trích xuất**: lấy lớp chữ của PDF bằng PyMuPDF. Trang không có chữ (bản scan) được OCR bằng
   Tesseract (`vie`, 300 dpi). File `.doc` đọc bằng `catdoc`, file `.docx` đọc trực tiếp XML.
4. **Làm sạch** (`clean.py`):
   - chuẩn hóa Unicode NFC;
   - bỏ khối chữ ký số, header trang Công báo, số trang, trang bìa sau và header
     "(Tiếp theo Công báo số …)" khi văn bản bị tách sang nhiều số Công báo;
   - nối các dòng bị ngắt cứng, giữ mỗi đơn vị **Phần / Chương / Mục / Điều / Khoản / Điểm**
     trên một dòng riêng để phục vụ Hierarchical Chunking (Task 2.1).

## Dữ liệu đầu ra (không commit, nằm trong `.gitignore`)

```
data/
├── raw/vanban.chinhphu.vn/
│   ├── resolved.json            # số hiệu -> docid
│   └── <docid>/
│       ├── detail.html          # trang chi tiết gốc (để parse lại khi cần)
│       └── files/*.pdf          # file đính kèm gốc
└── processed/vanban.chinhphu.vn/<docid>.json
```

Mỗi file `processed/<docid>.json` có dạng:

```json
{
  "metadata": {
    "document_number": "36/2024/QH15", "document_type": "Luật", "issuing_body": "Quốc hội",
    "title": "...", "issue_date": "2024-06-27", "effective_date": "2025-01-01",
    "url": "https://vanban.chinhphu.vn/?pageid=27160&docid=211194", "attachments": ["..."]
  },
  "text": "Chương I\nNHỮNG QUY ĐỊNH CHUNG\nĐiều 1. Phạm vi điều chỉnh\n...",
  "extraction": { "total_pages": 82, "ocr_pages": 0, "needs_review": false, "pages": ["..."] }
}
```

`needs_review: true` nghĩa là văn bản có trang phải OCR hoặc trang không trích được chữ.
OCR có thể nhận sai dấu hoặc số La Mã (VD: "Chương HI"), nên cần rà soát trước khi đưa vào kho
tri thức.

## Chuẩn hóa metadata & trạng thái hiệu lực (Task 1.3)

```bash
uv run python -m crawler normalize                 # trạng thái tính tại ngày hôm nay
uv run python -m crawler normalize --as-of 2024-06-01   # trạng thái tại một thời điểm trong quá khứ
```

Lệnh này đọc toàn bộ `data/processed/` và ghi ra `data/catalog.json`. Mỗi văn bản gồm các trường
`document_number`, `document_type` (Luật / Nghị định / Thông tư / Quyết định…), `issue_date`,
`effective_date`, `status`, `expiry_date`, các quan hệ `replaced_by` / `amended_by` / `replaces` /
`amends`, và `evidence` (câu nguyên văn làm căn cứ cho từng quan hệ).

Nguồn dữ liệu không cung cấp trạng thái hiệu lực, nên trạng thái được **suy ra từ nội dung các văn
bản trong kho**, cụ thể là từ điều khoản "Hiệu lực thi hành" và "Bãi bỏ":

| Câu trong văn bản Y | Kết luận về văn bản X |
|---|---|
| "X … hết hiệu lực kể từ ngày [Y] có hiệu lực" / "Các nghị định sau đây hết hiệu lực: a) X…" | X bị Y thay thế |
| "Bãi bỏ X" | X bị Y bãi bỏ |
| "Bãi bỏ Điều/khoản … của X" | X bị bãi bỏ một phần |
| Trích yếu "Sửa đổi, bổ sung … X" | X bị Y sửa đổi |
| "X có hiệu lực thi hành từ ngày D" | Ngày hiệu lực của X là D (VD: Luật 43/2024/QH15 cho Luật Đất đai 2024 có hiệu lực sớm từ 01/8/2024) |

Trạng thái tại thời điểm `as_of`:

| `status` | Ý nghĩa |
|---|---|
| `ACTIVE` | Còn hiệu lực |
| `AMENDED` | Còn hiệu lực nhưng đã bị sửa đổi, bổ sung hoặc bãi bỏ một phần |
| `EXPIRED` | Đã bị thay thế hoặc bãi bỏ toàn bộ, và văn bản thay thế đã có hiệu lực |
| `PENDING` | Chưa đến ngày có hiệu lực (bổ sung so với roadmap, để bộ lọc ở Task 3.2 không trả lời theo văn bản chưa có hiệu lực) |

Parser tránh các bẫy thường gặp: không coi các luật "đã được sửa đổi, bổ sung theo …" là bị thay
thế; bỏ qua số hiệu nằm trong đoạn trích dẫn “…”; không coi "có hiệu lực từ ngày Nghị quyết X hết
hiệu lực" là X bị thay thế; không lấy ngày hiệu lực riêng của một Điều làm ngày hiệu lực của cả
văn bản.

Lưu ý: trạng thái chỉ chính xác trong phạm vi kho dữ liệu. Nếu văn bản thay thế chưa được crawl
thì văn bản cũ vẫn hiện `ACTIVE`, vì vậy cần thêm văn bản liên quan vào `seeds.yaml`. Văn bản
`needs_review` (OCR) có thể bị sót quan hệ do lỗi nhận dạng chữ.

## Giới hạn hiện tại

- **vbpl.vn** (CSDL quốc gia về pháp luật) chặn truy cập từ IP nước ngoài (HTTP 403 từ WAF của
  site), nên chưa dùng được làm nguồn khi chạy trên cloud.
- File đính kèm không phải PDF/DOC/DOCX được ghi vào `skipped_attachments`.
