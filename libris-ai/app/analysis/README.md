# Tóm tắt & phân tích văn bản pháp lý (Task 4.4)

Người dùng tải lên hợp đồng lao động, hợp đồng thuê nhà hoặc văn bản hành chính (.pdf, .doc,
.docx; bản scan được OCR) hoặc dán nội dung. Libris trả về:

- loại văn bản, các bên, tóm tắt, tối đa 8 **điều khoản chính**;
- tối đa 6 **điểm cần lưu ý**, xếp theo mức độ: `high` (có dấu hiệu trái quy định bắt buộc / thiệt
  hại lớn), `medium` (bất lợi đáng kể, mơ hồ), `low` (nên thương lượng), `unclear` (kho dữ liệu
  chưa đủ căn cứ). Mỗi điểm có trích đoạn nguyên văn trong hợp đồng, lý do, **đánh giá có trích
  dẫn luật đã xác minh** và đề xuất sửa đổi.

```http
POST /analyze/stream          (multipart: file | text; cần X-Internal-Token)
```

Luồng SSE: `progress` `{step, message}` (`read_file` → `read` → `retrieve` × số điểm →
`assess`) rồi `done` (kết quả) hoặc `error` `{message}`. Lỗi đầu vào phát hiện được ngay (thiếu
dữ liệu, sai định dạng, file > `ANALYSIS_MAX_UPLOAD_MB`) trả HTTP 422/413 trước khi mở luồng.

## Cách làm (`contract.py`)

1. **Đọc hợp đồng** – một lượt LLM ở chế độ JSON (`response_format: json_object`): tóm tắt, điều
   khoản chính, các điểm cần kiểm tra. Mỗi điểm kèm trích dẫn nguyên văn và một **câu hỏi pháp lý**
   độc lập (VD "Thời gian thử việc tối đa với công việc cần trình độ cao đẳng là bao lâu?"). Ở bước
   này mô hình không được kết luận hợp pháp hay không.
2. **Dò trích đoạn** trong văn bản gốc (bỏ qua khác biệt khoảng trắng, hoa/thường): tìm thấy thì
   có vị trí để giao diện bôi vàng; không thấy thì đánh dấu "không tìm thấy nguyên văn".
3. **Tra luật** – mỗi câu hỏi pháp lý đi qua Hybrid Search + Rerank như hỏi đáp, **chỉ trong quy
   định đang có hiệu lực**; bỏ đoạn có điểm rerank < `ANSWER_MIN_RERANK_SCORE`.
4. **Đối chiếu** – lượt LLM thứ hai đánh giá từng điểm CHỈ dựa trên các đoạn luật tìm được, mỗi
   nhận định pháp lý phải có thẻ `[Điều X, Khoản Y - Số hiệu]`. Thẻ được xác minh như câu trả lời
   hỏi đáp (`citations.py`); thẻ không khớp được báo trong `warnings`. Điểm bị đánh giá
   `high`/`medium` mà **không có trích dẫn hợp lệ nào** được gắn cờ "chưa có căn cứ pháp lý được
   xác minh; nên tham khảo ý kiến luật sư".

JSON sai định dạng thì gọi lại một lần. Văn bản dài hơn `ANALYSIS_MAX_CHARS` (mặc định 60.000 ký
tự) chỉ được phân tích phần đầu, có cảnh báo.

| Biến | Mặc định | |
|---|---|---|
| `ANALYSIS_MAX_UPLOAD_MB` | 10 | |
| `ANALYSIS_MAX_CHARS` | 60000 | phần đưa cho LLM |
| `ANALYSIS_MAX_ISSUES` | 6 | mỗi điểm tốn một lượt tra luật (~8 giây trên CPU với `RERANK_CANDIDATES=10`) |
| `ANALYSIS_PASSAGES_PER_ISSUE` | 3 | |

## Quyền riêng tư

Văn bản **không được lưu** vào DB hay ổ đĩa: chỉ nằm trong bộ nhớ trong lúc xử lý. Tuy nhiên nội
dung được gửi tới nhà cung cấp LLM (mặc định Gemini); giao diện thông báo điều này cho người dùng.
Với gói miễn phí của Gemini, Google có thể dùng dữ liệu gửi lên để cải thiện sản phẩm – khi triển
khai thật cho hợp đồng nhạy cảm nên dùng gói trả phí hoặc mô hình tự triển khai.

## Giới hạn

- Chỉ đối chiếu với văn bản có trong kho dữ liệu; điểm không tìm được căn cứ là `unclear`, không
  có nghĩa điều khoản đó hợp pháp.
- Mô hình có thể bỏ sót điểm bất lợi; kết quả chỉ để tham khảo, không thay thế luật sư.
