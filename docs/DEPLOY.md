# Triển khai Libris lên cloud (Task 6.1)

```mermaid
flowchart LR
  U[Người dùng] -->|HTTPS| W[libris-web<br/>Next.js – Vercel]
  W -->|REST + SSE, JWT| A[libris-api<br/>NestJS – Render web service]
  A -->|X-Internal-Token<br/>mạng nội bộ| AI[libris-ai<br/>FastAPI + bge-m3 + reranker<br/>Render private service]
  A --> DB[(PostgreSQL + pgvector<br/>Neon / Supabase)]
  AI --> DB
  AI --> R[(Redis 8<br/>Semantic Cache)]
  AI -->|HTTPS| G[Gemini API]
```

| Thành phần | Nền tảng | Ghi chú |
|---|---|---|
| PostgreSQL + pgvector | **Neon** hoặc **Supabase** | Dữ liệu hiện ~102 MB: vừa gói miễn phí của cả hai (0,5 GB) |
| libris-api | Render web service (Docker) | ~50 MB RAM: gói nhỏ nhất là đủ |
| libris-ai | Render **private** service (Docker) | Không mở ra Internet; cần **≥ 2 GB RAM** (đo ở dưới) |
| Redis 8 | Render private service (image `redis:8.2-alpine`) | Tùy chọn – không có thì cache tự tắt |
| libris-web | **Vercel** | |

`render.yaml` ở gốc repo khai báo sẵn ba dịch vụ trên Render (Blueprint). Các bước dưới đây cần tài
khoản của bạn trên Neon/Supabase, Render, Vercel và Google AI Studio.

## 0. Chuẩn bị

- Render và Vercel deploy từ nhánh **`main`**: merge `develop` vào `main` khi muốn phát hành.
- Khóa Gemini: Google AI Studio -> Get API key. Gói miễn phí giới hạn số request mỗi ngày (VD
  `gemini-3.6-flash` chỉ 20 request/ngày) – demo cho nhiều người nên dùng gói trả phí.

## 1. Cơ sở dữ liệu

**Neon**: tạo project ở region gần Việt Nam (AWS Singapore) -> Connection details -> bỏ chọn
"Connection pooling" để lấy chuỗi kết nối **trực tiếp** (`...neon.tech/neondb?sslmode=require`).

**Supabase** (thay cho Neon): tạo project (region Singapore) -> Connect -> **Session pooler** hoặc
Direct connection (cổng 5432). Không dùng Transaction pooler (cổng 6543): psycopg dùng prepared
statement, không chạy qua PgBouncer chế độ transaction.

Chuyển schema và kho văn bản từ máy đang có dữ liệu (cần Docker):

```bash
TARGET_DATABASE_URL='postgresql://USER:PASS@HOST/DB?sslmode=require' scripts/migrate_to_cloud.sh
```

Script chạy toàn bộ migration (extension `vector`, bảng, chỉ mục HNSW) rồi copy 4 bảng kho văn bản
(văn bản, quan hệ hiệu lực, Điều/Khoản bị bãi bỏ, đoạn luật kèm embedding) và so khớp số dòng.
Tài khoản và lịch sử chat không được copy. DB đích phải còn trống.

## 2. Backend trên Render

Render Dashboard -> **New -> Blueprint** -> chọn repo -> Render đọc `render.yaml` và hỏi các biến:

| Biến | Dịch vụ | Giá trị |
|---|---|---|
| `DATABASE_URL` | libris-api, libris-ai | chuỗi kết nối ở bước 1 |
| `LLM_API_KEY` | libris-ai | khóa Gemini |
| `WEB_ORIGIN` | libris-api | domain Vercel ở bước 3 (tạm điền `http://localhost:3000`, sửa sau) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | libris-api | tài khoản quản trị đầu tiên (mật khẩu ≥ 8 ký tự) |

`JWT_SECRET` và `INTERNAL_API_TOKEN` được Render sinh ngẫu nhiên; libris-api tự nhận địa chỉ và
token của libris-ai qua `fromService`. Lần deploy đầu libris-ai tải mô hình (~4,5 GB) vào disk
`/models` nên mất vài phút; các lần sau dùng lại.

Kiểm tra: `https://<libris-api>.onrender.com/health` trả `{"status":"ok"}`.

### RAM của libris-ai (đo thực tế, CPU)

Chạy image production với giới hạn RAM bằng `docker update --memory`, gửi liên tiếp các câu hỏi mới
(chưa có trong cache) và một lần phân tích hợp đồng:

| Giới hạn RAM | Kết quả |
|---|---|
| 2 GB | 5 câu hỏi mới (11–14 giây mỗi câu) + phân tích hợp đồng (70 giây): ổn định, dùng tối đa ~1,2 GB |
| 1,5 GB | trả lời được câu đầu nhưng **tiến trình bị dừng và khởi động lại** sau vài câu – không đủ |

Khuyến nghị gói **≥ 2 GB** (Render `standard`) để còn dư cho tải văn bản/phân tích hợp đồng
(OCR). Máy nhỏ hơn: đặt `RERANKER_ENABLED=false` (bỏ mô hình reranker) – chất lượng truy xuất giảm
rõ (Context Precision@5 0,775 -> 0,588, xem `libris-ai/eval/README.md`).

Thời gian trả lời: 8–20 giây (rerank trên CPU + LLM); câu hỏi đã có trong Semantic Cache ~0,25 giây
tính cả đường đi qua libris-api. `RERANK_CANDIDATES=10` (mặc định trong `render.yaml`) nhanh gấp đôi
20 trên CPU, đổi lại Context Precision@5 0,744 thay vì 0,775.

## 3. Giao diện trên Vercel

Vercel -> **Add New -> Project** -> chọn repo -> **Root Directory: `libris-web`** (Next.js được nhận
tự động) -> Environment Variables:

| Biến | Giá trị |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<libris-api>.onrender.com` |

Sau khi có domain Vercel, sửa `WEB_ORIGIN` của libris-api trên Render thành domain đó (CORS) rồi
deploy lại libris-api.

## 4. Kiểm tra sau khi triển khai

1. Mở domain Vercel -> đăng nhập bằng `ADMIN_EMAIL` -> hỏi "Không đội mũ bảo hiểm khi đi xe máy bị
   phạt bao nhiêu?" -> câu trả lời hiện dần, có thẻ trích dẫn; bấm thẻ mở nguyên văn.
2. Hỏi lại đúng câu đó: trả lời gần như tức thì, có dòng "Trả lời từ bộ nhớ đệm".
3. Trang "Phân tích văn bản": dán một hợp đồng ngắn -> có tóm tắt và các điểm cần lưu ý.

## Chạy bản production trên một máy (không cần cloud)

```bash
cp .env.example .env    # điền JWT_SECRET, INTERNAL_API_TOKEN, LLM_API_KEY
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose run --rm migrate
```

libris-api ở cổng 4000, libris-ai ở cổng 8000; giao diện chạy `npm run build && npm start` trong
`libris-web` với `NEXT_PUBLIC_API_URL=http://localhost:4000`.

## Bảo mật

- libris-ai là dịch vụ **riêng tư**: chỉ libris-api gọi được, kèm `X-Internal-Token`. Không mở ra
  Internet.
- Mọi khóa (Gemini, JWT, token nội bộ, mật khẩu DB) chỉ đặt trong biến môi trường của nền tảng,
  không commit vào repo.
- Container chạy bằng user không phải root.
- Access token trên web đang lưu trong `localStorage`; trước khi mở cho nhiều người dùng nên chuyển
  sang cookie `HttpOnly`.

## Giới hạn đã biết

- File Admin tải lên chỉ cần trong lúc xử lý (nội dung đã lưu vào DB); thư mục `data/uploads` của
  container không cần giữ lâu dài.
- Neon (gói miễn phí) tự tạm dừng DB khi không dùng: request đầu tiên sau đó chậm thêm vài giây.
- `render.yaml` được viết theo đặc tả Blueprint của Render nhưng chưa được chạy thử trên tài khoản
  Render thật (môi trường phát triển không truy cập được Render); Render kiểm tra file khi import và
  báo lỗi nếu có trường không hợp lệ. Hai image Docker và toàn bộ luồng production đã được chạy thử
  bằng Docker Compose.
