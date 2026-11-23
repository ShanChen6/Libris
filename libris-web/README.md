# libris-web

Giao diện Next.js của Libris.

```bash
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:4000 (libris-api)
npm install
npm run dev                     # http://localhost:3000
npm run lint && npm run build
```

| Trang | Mô tả |
|---|---|
| `/` | giới thiệu |
| `/login` | đăng nhập / đăng ký (gọi `/auth/*` của libris-api) |
| `/chat` | hỏi đáp: câu trả lời hiện từng chữ qua SSE, cảnh báo hiệu lực, danh sách căn cứ pháp lý; nút **Dừng** hủy luồng. Bấm thẻ trích dẫn để mở ngăn xem văn bản gốc |

## Ngăn xem văn bản gốc (Task 4.3)

Màn hình rộng chia 2 khung: hội thoại bên trái, văn bản gốc bên phải. Trên điện thoại, văn bản gốc
phủ toàn màn hình, có nút đóng.

- Khi đang stream, thẻ trích dẫn chưa bấm được (chưa xác minh). Khi nhận `done`, chỉ các thẻ
  **đã xác minh** (`citations`) mới thành nút màu xanh. Thẻ có dạng trích dẫn mà không xác minh
  được thì hiện viền đứt, không bấm được.
- Bấm thẻ sẽ tải nguyên văn (`GET /documents/:id/text`; mỗi văn bản chỉ tải một lần), bôi vàng
  đoạn `char_start`–`char_end` và cuộn tới đó. Nếu thẻ trích tới **Điểm** mà đoạn luật đã lưu là
  cả Khoản, Điểm đó được bôi đậm hơn bên trong Khoản.
- Phần đầu ngăn xem hiện trạng thái hiệu lực, ngày hiệu lực, link nguồn, cảnh báo nếu Điều/Khoản đã
  bị bãi bỏ hoặc sửa đổi, và cảnh báo nếu văn bản được nhận dạng từ bản scan (OCR).
- Vị trí trích dẫn trong câu trả lời và vị trí đoạn luật trong nguyên văn đều tính theo code point
  (Python), nên phía web cắt chuỗi bằng `Array.from` (`src/lib/citations.ts`).

`src/lib/api.ts` là client của libris-api; `src/lib/sse.ts` đọc luồng SSE từ `fetch` (không dùng
`EventSource` vì cần `POST` và header `Authorization`).

Giới hạn hiện tại: access token lưu trong `localStorage` (đơn giản cho giai đoạn này; nên chuyển
sang cookie `HttpOnly` trước khi triển khai thật); chưa có danh sách hội thoại cũ (API đã có
`GET /chat/sessions`).
