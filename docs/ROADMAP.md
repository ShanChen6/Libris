# LỘ TRÌNH TRIỂN KHAI DỰ ÁN: LIBRIS – TRỢ LÝ PHÁP LUẬT (HỆ THỐNG HỎI ĐÁP & TRA CỨU PHÁP LUẬT RAG CHUYÊN SÂU)

## 1. Tổng quan & Kiến trúc hệ thống
- **Tên dự án:** Libris – Trợ lý Pháp luật
- **Mục tiêu cốt lõi:** Xây dựng hệ thống trợ lý trí tuệ nhân tạo hỗ trợ người dân và chuyên viên pháp lý tra cứu, hỏi đáp, tóm tắt và đối chiếu văn bản quy phạm pháp luật Việt Nam (Luật, Nghị định, Thông tư) với độ chính xác cao, có trích dẫn điều khoản nguyên văn và kiểm soát chặt chẽ hiệu lực văn bản theo thời gian.
- **Kiến trúc kỹ thuật (Hybrid Microservices):**
  - **Frontend:** Next.js (App Router), TailwindCSS, Shadcn/UI (hỗ trợ Streaming Chat và Interactive Citation Viewer).
  - **Backend Web & Auth:** Node.js (NestJS), JWT Authentication & RBAC, lưu trữ lịch sử hội thoại.
  - **AI & Search Engine:** Python (FastAPI), LangChain / LlamaIndex, Mô hình Embedding (`BAAI/bge-m3`), Mô hình Reranker (`bge-reranker-v2-m3`), LLM (OpenAI / Gemini / Qwen).
  - **Database & Vector Store:** PostgreSQL kết hợp extension `pgvector` (Vector Search) và `tsvector` (Full-text Search/BM25), Redis (Caching).

---

## 2. Lộ trình triển khai chi tiết (12 Tuần)

### GIAI ĐOẠN 1: Thu thập, Chuẩn hóa Dữ liệu & Thiết kế Cơ sở dữ liệu (Tuần 1 – Tuần 2)
*Mục tiêu: Xây dựng kho văn bản pháp luật Việt Nam sạch, có cấu trúc phân cấp rõ ràng và gắn nhãn trạng thái hiệu lực pháp lý.*

- [x] **Task 1.1: Khởi tạo hạ tầng & Môi trường phát triển**
  - Khởi tạo 3 phân hệ: `libris-web` (Next.js), `libris-api` (NestJS), và `libris-ai` (Python FastAPI).
  - Cấu hình Docker Compose chạy PostgreSQL (đã kích hoạt `CREATE EXTENSION vector;`) và Redis.
- [x] **Task 1.2: Thu thập dữ liệu pháp luật (Data Crawling)**
  - Viết script Python (Playwright / BeautifulSoup) thu thập văn bản từ Cổng thông tin điện tử Chính phủ / Cơ sở dữ liệu quốc gia về pháp luật.
  - Tập trung làm sạch dữ liệu cho các bộ luật trọng điểm (VD: Luật Đất đai, Luật Trật tự an toàn giao thông đường bộ, Bộ luật Lao động, Luật Hôn nhân và Gia đình) cùng các Nghị định, Thông tư hướng dẫn liên quan.
- [x] **Task 1.3: Bóc tách Siêu dữ liệu (Metadata Extraction)**
  - Chuẩn hóa các trường định danh bắt buộc cho mỗi văn bản:
    - `document_number`: Số hiệu văn bản (VD: `168/2024/NĐ-CP`).
    - `document_type`: Loại văn bản (`Luật`, `Nghị định`, `Thông tư`, `Quyết định`).
    - `issue_date`: Ngày ban hành & `effective_date`: Ngày có hiệu lực.
    - `status`: Trạng thái hiệu lực (`ACTIVE` - Còn hiệu lực, `EXPIRED` - Hết hiệu lực, `AMENDED` - Bị sửa đổi/bổ sung).
- [x] **Task 1.4: Thiết kế Database PostgreSQL + `pgvector`**
  - Bảng `Users` & `ChatSessions` & `ChatMessages` (quản lý người dùng, phiên hội thoại và danh sách các trích dẫn đi kèm từng câu trả lời).
  - Bảng `LegalDocuments` (lưu nguyên văn và metadata của văn bản luật).
  - Bảng `LegalChunks` (lưu từng đoạn luật đã cắt nhỏ, kèm cột `embedding vector(1024)` và cột `search_vector tsvector`).

---

### GIAI ĐOẠN 2: Pipeline Xử lý Ngôn ngữ Luật — Legal Chunking & Embedding (Tuần 3 – Tuần 4)
*Mục tiêu: Giải quyết bài toán cắt văn bản luật không làm đứt gãy ngữ cảnh pháp lý của từng Điều/Khoản.*

- [x] **Task 2.1: Phân tách Văn bản theo Cấu trúc Phân cấp (Hierarchical Chunking)**
  - Xây dựng bộ phân tích cú pháp (Parser) bằng Regex nhận diện đúng cấu trúc văn bản hành chính Việt Nam: **Phần → Chương → Mục → Điều → Khoản → Điểm**.
  - **Quy tắc bảo toàn ngữ cảnh:** Mỗi đoạn dữ liệu (`chunk`) sau khi cắt bắt buộc phải được gắn thêm tiền tố ngữ cảnh ở đầu đoạn (VD: `[Văn bản: Nghị định 168/2024/NĐ-CP | Chương II | Điều 7: Xử phạt người điều khiển xe mô tô...]`) để mô hình nhúng hiểu trọn vẹn chủ thể áp dụng.
- [x] **Task 2.2: Tạo Vector nhúng (Embedding) & Chỉ mục tìm kiếm**
  - Sử dụng mô hình `BAAI/bge-m3` (hỗ trợ tốt tiếng Việt và độ dài lên tới 8192 tokens) để sinh vector cho toàn bộ `LegalChunks`.
  - Tạo chỉ mục **HNSW** cho cột `embedding` (tăng tốc tìm kiếm ngữ nghĩa) và chỉ mục **GIN** cho cột `search_vector` (tăng tốc tìm kiếm từ khóa tiếng Việt).

---

### GIAI ĐOẠN 3: Lõi Truy xuất Thông minh — Hybrid Search & Chống Ảo giác (Tuần 5 – Tuần 7)
*Mục tiêu: Đảm bảo hệ thống tìm trúng điều luật chính xác nhất và trả lời trung thực 100% theo căn cứ pháp lý.*

- [x] **Task 3.1: Xây dựng Tìm kiếm lai (Hybrid Search với thuật toán RRF)**
  - Viết truy vấn kết hợp đồng thời 2 luồng tìm kiếm trên PostgreSQL và hợp nhất điểm số bằng **Reciprocal Rank Fusion (RRF)**:
    - *Vector Search:* Bắt ý định câu hỏi đời thường (VD: *"Đi xe máy không gương chiếu hậu bên trái có bị phạt không?"*).
    - *Keyword Search (Full-text Search):* Bắt chính xác số hiệu văn bản, điều khoản hoặc thuật ngữ pháp lý đặc thù.
- [x] **Task 3.2: Bộ lọc Hiệu lực Pháp lý Thông minh (Temporal & Status Filtering)**
  - Mặc định hệ thống chỉ truy xuất các `LegalChunks` thuộc văn bản có trạng thái `ACTIVE` (Còn hiệu lực) để tránh tư vấn nhầm luật cũ.
  - Bổ sung bộ nhận diện ý định (Query Router): Nếu người dùng hỏi so sánh luật cũ và mới, tự động mở rộng bộ lọc sang cả văn bản `EXPIRED`.
- [x] **Task 3.3: Tái xếp hạng Kết quả (Cross-Encoder Reranking)**
  - Đưa Top 20 đoạn luật tìm được từ Hybrid Search qua mô hình Reranker (`bge-reranker-v2-m3`) để chấm điểm lại mức độ liên quan trực tiếp với câu hỏi, chọn ra **Top 5 đoạn luật tinh túy nhất**.
- [x] **Task 3.4: Thiết kế System Prompt Chống Ảo giác (Strict Citation Prompting)**
  - Thiết lập quy tắc bắt buộc cho LLM:
    - Chỉ sử dụng thông tin nằm trong Top 5 đoạn luật được cung cấp.
    - Bắt buộc chèn thẻ trích dẫn chuẩn xác ngay sau mỗi luận điểm theo định dạng: `[Điều X, Khoản Y - Số hiệu văn bản]`.
    - Nếu kho dữ liệu không có điều luật điều chỉnh vấn đề người dùng hỏi, thẳng thắn từ chối trả lời và khuyến nghị tham vấn luật sư thay vì tự suy diễn.

---

### GIAI ĐOẠN 4: Phát triển Backend API & Giao diện Trải nghiệm Người dùng (Tuần 8 – Tuần 10)
*Mục tiêu: Xây dựng giao diện trợ lý pháp luật trực quan, phản hồi tức thì và cho phép kiểm chứng nguồn luật ngay trên màn hình.*

- [x] **Task 4.1: Xây dựng Backend Quản trị (NestJS)**
  - Xây dựng hệ thống đăng ký/đăng nhập (JWT), phân quyền người dùng và quản trị viên.
  - Xây dựng API quản lý kho văn bản luật: Cho phép Admin tải lên văn bản luật mới (file `.docx` hoặc `.pdf`), hệ thống tự động gọi sang FastAPI để chạy pipeline bóc tách và cập nhật vào VectorDB.
- [x] **Task 4.2: Tích hợp Streaming Response (Server-Sent Events)**
  - Kết nối luồng dữ liệu từ `FastAPI -> NestJS -> Next.js` qua SSE để câu trả lời của Chatbot hiển thị mượt mà từng chữ theo thời gian thực kèm danh sách metadata các điều luật đã trích dẫn.
- [x] **Task 4.3: Giao diện Đối chiếu Trích dẫn Tương tác (Interactive Citation Viewer)**
  - Thiết kế giao diện Next.js (TailwindCSS + Shadcn/UI) chia 2 khu vực trực quan:
    - **Khung bên trái:** Giao diện hội thoại Chatbot với các thẻ trích dẫn màu xanh có thể bấm vào được.
    - **Khung bên phải (Ngăn xem văn bản gốc):** Khi người dùng bấm vào thẻ trích dẫn `[Điều 7 - Nghị định 168/2024/NĐ-CP]`, hệ thống tự động mở nguyên văn văn bản đó và **bôi vàng (highlight)** chính xác đoạn luật được trích dẫn để người dùng tự kiểm chứng.
- [x] **Task 4.4: Tính năng Tóm tắt & Phân tích Văn bản Pháp lý**
  - Cho phép người dùng tải lên một file hợp đồng lao động, hợp đồng thuê nhà hoặc văn bản hành chính để Libris tóm tắt các điều khoản quan trọng và cảnh báo các điểm bất lợi/rủi ro pháp lý.

---

### GIAI ĐOẠN 5: Đánh giá Độ chính xác (RAG Evaluation) & Tối ưu Hiệu năng (Tuần 11)
*Mục tiêu: Đo lường chất lượng trả lời của Libris bằng các chỉ số định lượng khoa học.*

- [x] **Task 5.1: Xây dựng Bộ dữ liệu Kiểm thử Chuẩn (Golden Dataset)**
  - Biên soạn 100 câu hỏi tình huống pháp luật thực tế (từ dễ đến phức tạp, bao gồm cả câu hỏi bẫy về luật hết hiệu lực) kèm đáp án chuẩn và mã điều luật tham chiếu.
- [x] **Task 5.2: Đánh giá tự động bằng Framework RAGAS**
  - Chạy đánh giá tự động để tối ưu hóa tham số (chunk size, trọng số Hybrid Search) dựa trên 3 chỉ số:
    - **Faithfulness (Độ trung thực):** Đảm bảo câu trả lời bám sát 100% văn bản luật, không bịa đặt.
    - **Context Precision (Độ chính xác truy xuất):** Đảm bảo điều luật đúng luôn nằm trong Top đầu kết quả tìm kiếm.
    - **Answer Relevancy (Độ liên quan):** Câu trả lời đi thẳng vào trọng tâm thắc mắc của người dùng.
- [x] **Task 5.3: Tối ưu Tốc độ với Semantic Caching (Redis)**
  - Lưu bộ nhớ đệm (Cache) các câu hỏi pháp luật phổ biến trên Redis giúp phản hồi gần như tức thì (< 0.5 giây) và tiết kiệm chi phí gọi API mô hình ngôn ngữ.

---

### GIAI ĐOẠN 6: Triển khai Cloud (Deploy) & Hoàn thiện Tài liệu Dự án (Tuần 12)
*Mục tiêu: Đưa Libris lên môi trường Internet ổn định và hoàn thiện hồ sơ trình bày.*

- [ ] **Task 6.1: Triển khai Hạ tầng (Deployment)**
  - Deploy PostgreSQL (`pgvector`) lên **Supabase** hoặc **Neon**.
  - Đóng gói Docker cho dịch vụ `libris-ai` (FastAPI) và `libris-api` (NestJS), triển khai lên **Render** hoặc **Railway**.
  - Deploy giao diện `libris-web` (Next.js) lên **Vercel**.
- [ ] **Task 6.2: Hoàn thiện Báo cáo & Kịch bản Demo**
  - Trình bày sơ đồ kiến trúc Hybrid Search, cơ chế kiểm soát hiệu lực văn bản theo thời gian và bảng kết quả đánh giá RAGAS.
  - Chuẩn bị kịch bản Demo thực tế: Hỏi tình huống giao thông/đất đai -> Bấm vào trích dẫn để đối chiếu nguyên văn điều luật -> Thử nghiệm hỏi quy định cũ đã hết hiệu lực để chứng minh hệ thống tự động cập nhật theo luật mới nhất.
