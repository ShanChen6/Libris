# libris-api

Backend NestJS 12 của Libris: đăng ký/đăng nhập (JWT), phân quyền người dùng và quản trị viên,
quản lý kho văn bản luật. Phần xử lý văn bản (OCR, cắt đoạn, embedding) và hỏi đáp nằm ở
`libris-ai`; libris-api gọi sang bằng token nội bộ.

## Chạy

```bash
cp .env.example .env          # điền JWT_SECRET (openssl rand -base64 32), AI_SERVICE_TOKEN
npm install                    # npm 10 có lỗi với dependency của Nest 12: dùng npm 11+
npm run start:dev              # http://localhost:4000
```

Cần PostgreSQL đã chạy migration (`docker compose run --rm migrate` ở gốc repo). Đặt `ADMIN_EMAIL` và
`ADMIN_PASSWORD` để tạo tài khoản quản trị đầu tiên khi khởi động (bỏ qua nếu email đã tồn tại).

| Biến | Ý nghĩa |
|---|---|
| `DATABASE_URL` | PostgreSQL dùng chung với libris-ai |
| `JWT_SECRET` | khóa ký access token, **≥ 32 byte** (ứng dụng không khởi động nếu ngắn hơn) |
| `JWT_TTL` | thời hạn access token, mặc định `2h` |
| `AI_SERVICE_URL`, `AI_SERVICE_TOKEN` | địa chỉ libris-ai; token phải trùng `INTERNAL_API_TOKEN` của libris-ai |
| `WEB_ORIGIN` | origin của libris-web cho CORS (nhiều origin cách nhau dấu phẩy) |
| `MAX_UPLOAD_MB` | dung lượng file tải lên tối đa, mặc định 30 |

## API

Mọi route mặc định **yêu cầu đăng nhập** (`Authorization: Bearer <accessToken>`); route không khai
báo quyền bị từ chối.

| Method & đường dẫn | Quyền | Mô tả |
|---|---|---|
| `GET /health` | công khai | kiểm tra dịch vụ |
| `POST /auth/register` | công khai | `{ email, password (≥ 8 ký tự), fullName? }` → `{ user, accessToken, expiresIn }` |
| `POST /auth/login` | công khai | `{ email, password }` → `{ user, accessToken, expiresIn }`; sai email hay sai mật khẩu đều trả 401 cùng nội dung |
| `GET /auth/me` | đã đăng nhập | người dùng hiện tại |
| `GET /documents?status=ACTIVE,AMENDED&type=Luật&q=đất đai` | đã đăng nhập | danh sách văn bản, kèm trạng thái hiệu lực và số đoạn |
| `GET /documents/:id` | đã đăng nhập | chi tiết văn bản, quan hệ thay thế/sửa đổi, các Điều/Khoản bị bãi bỏ |
| `POST /admin/documents` | ADMIN | multipart: `file` (.pdf/.doc/.docx), `documentNumber`, `title`, `documentType?`, `issuingBody?`, `signer?`, `issueDate?`, `effectiveDate?` → 202 `{ jobId, statusUrl }` |
| `GET /admin/ingestions`, `GET /admin/ingestions/:id` | ADMIN | tiến trình xử lý: `queued → processing (extract, metadata, chunk, embed) → done / failed` |
| `DELETE /admin/documents/:id` | ADMIN | xóa văn bản cùng các đoạn luật, tính lại trạng thái hiệu lực các văn bản liên quan |
| `POST /chat/sessions` | đã đăng nhập | tạo hội thoại `{ title? }` |
| `GET /chat/sessions`, `GET /chat/sessions/:id` | chủ hội thoại | danh sách hội thoại; chi tiết kèm tin nhắn và trích dẫn |
| `PATCH /chat/sessions/:id`, `DELETE /chat/sessions/:id` | chủ hội thoại | đổi tên / xóa hội thoại |
| `POST /chat/sessions/:id/messages` | chủ hội thoại | `{ content }` → luồng SSE (xem dưới); 20 câu hỏi mỗi phút |
| `GET /admin/users?limit=&after=` | ADMIN | danh sách người dùng (phân trang theo con trỏ) |
| `PATCH /admin/users/:id/role` | ADMIN | `{ role: "USER" \| "ADMIN" }`; không hạ được quản trị viên cuối cùng (409) |

Lỗi validation trả 400 với `message` là danh sách lỗi theo trường; 401 là chưa đăng nhập hoặc
token sai/hết hạn; 403 là không đủ quyền.

## Thiết kế

- **Xác thực**: `@nestjs/authentication`. Mật khẩu băm bằng scrypt (`PasswordHasher`); kiểm tra
  mật khẩu luôn chạy cả khi email không tồn tại, nên thời gian phản hồi không làm lộ email nào đã
  đăng ký. Access token JWT HS256 ngắn hạn, không dùng refresh token: hết hạn thì đăng nhập lại.
  `/auth/*` giới hạn 10 lần mỗi phút mỗi IP.
- **Phân quyền**: `@nestjs/authorization`, `AdminPolicy` cho mọi route `/admin/*`. Người dùng và
  vai trò được **đọc lại từ DB ở mỗi request** (không lấy từ token), nên khóa tài khoản hay đổi vai
  trò có hiệu lực ngay, kể cả với token đã phát.
- **Dữ liệu**: `pg` với truy vấn có tham số; schema do migration SQL ở `db/migrations` quản lý
  (chung với libris-ai). Email trùng được bắt bằng ràng buộc unique (409), không kiểm tra trước.
- **Tải văn bản lên**: libris-api nhận file và kiểm tra quyền, định dạng, thông tin bắt buộc, rồi
  chuyển sang `POST /ingest` của libris-ai kèm `X-Internal-Token`. libris-ai xử lý nền và ghi tiến
  trình vào bảng `ingestion_jobs`, libris-api đọc thẳng từ đó. Khi văn bản mới thay thế hoặc bãi bỏ
  văn bản cũ, hàm SQL `recompute_document_status()` cập nhật trạng thái văn bản cũ ngay.

## Luồng trả lời (SSE)

`POST /chat/sessions/:id/messages` trả `text/event-stream`. Luồng đi `FastAPI → NestJS → Next.js`:
libris-api lưu câu hỏi, gọi `POST /answer/stream` của libris-ai rồi chuyển tiếp từng sự kiện.

| Sự kiện | Dữ liệu |
|---|---|
| `start` | `{ userMessageId }` – gửi ngay, trước khi truy xuất |
| `meta` | `{ plan, sources }` – các đoạn luật tìm được |
| `delta` | `{ text }` – từng mẩu câu trả lời |
| `done` | kết quả cuối như `POST /answer` của libris-ai (câu trả lời đã xác minh trích dẫn, `citations`, `warnings`, `refused`) kèm `messageId`. Client thay nội dung đã hiển thị bằng `answer` ở đây |
| `error` | `{ message }` |

Câu trả lời và các trích dẫn đã xác minh được lưu vào `chat_messages` / `message_citations` khi
nhận `done`. Client ngắt kết nối giữa chừng thì libris-api hủy luôn request sang libris-ai (không
tốn lượt gọi LLM) và không lưu câu trả lời dở.

## Kiểm thử

```bash
npm test                                   # unit
LIBRIS_TEST_DATABASE_URL=postgresql://libris:libris@localhost:5432/libris npm run test:e2e
npm run lint
```

Test e2e chạy toàn bộ migration vào một schema PostgreSQL tạm, đi qua route thật (đăng ký, đăng
nhập, phân quyền, tải văn bản lên với libris-ai giả lập, xóa văn bản và tính lại hiệu lực, giới hạn
đăng nhập) rồi xóa schema đó.
