# Crawler văn bản pháp luật (Task 1.2)

Thu thập văn bản quy phạm pháp luật từ **Hệ thống văn bản của Chính phủ**
([vanban.chinhphu.vn](https://vanban.chinhphu.vn)). Toàn văn lấy từ file PDF bản Công báo trên
`datafiles.chinhphu.vn`.

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

OCR cho PDF dạng ảnh scan cần Tesseract kèm dữ liệu tiếng Việt:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-vie   # Ubuntu/Debian
brew install tesseract tesseract-lang                     # macOS
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
   Tesseract (`vie`, 300 dpi).
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

## Giới hạn hiện tại

- **Trạng thái hiệu lực** (`ACTIVE` / `EXPIRED` / `AMENDED`) chưa có trên nguồn này; sẽ được
  chuẩn hóa ở Task 1.3.
- **vbpl.vn** (CSDL quốc gia về pháp luật) chặn truy cập từ IP nước ngoài (HTTP 403 từ WAF của
  site), nên chưa dùng được làm nguồn khi chạy trên cloud.
- Crawler chỉ tải file PDF; file đính kèm định dạng khác được ghi vào `skipped_attachments`.
