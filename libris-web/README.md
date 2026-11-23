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
| `/chat` | hỏi đáp: câu trả lời hiện từng chữ qua SSE, thẻ trích dẫn `[Điều X - Số hiệu]` tô màu, cảnh báo hiệu lực, danh sách căn cứ pháp lý; nút **Dừng** hủy luồng |

`src/lib/api.ts` là client của libris-api; `src/lib/sse.ts` đọc luồng SSE từ `fetch` (không dùng
`EventSource` vì cần `POST` và header `Authorization`).

Giới hạn hiện tại: access token lưu trong `localStorage` (đơn giản cho giai đoạn này; nên chuyển
sang cookie `HttpOnly` trước khi triển khai thật); chưa có danh sách hội thoại cũ và ngăn xem văn bản
gốc (Task 4.3).
