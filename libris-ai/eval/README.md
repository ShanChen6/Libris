# Đánh giá Libris (Giai đoạn 5)

| | Lệnh | Cần LLM |
|---|---|---|
| Kiểm tra bộ dữ liệu với kho | `uv run python eval/check_golden.py` | không |
| Đánh giá truy xuất (nhiều cấu hình) | `uv run python eval/eval_retrieval.py` | không |
| Sinh câu trả lời | `uv run python eval/eval_answers.py generate [--run TÊN]` | có |
| Chấm RAGAS | `uv sync --group eval` rồi `uv run python eval/eval_answers.py ragas [--judge-model M]` | có |
| Tổng hợp chỉ số | `uv run python eval/eval_answers.py report [--run TÊN]` | không |
| Chọn ngưỡng Semantic Cache | `uv run python eval/calibrate_cache.py` | không |

Các script ghi từng câu vào `results/*.jsonl` và bỏ qua câu đã có: hết quota thì chạy lại để làm
tiếp. Điểm rerank và câu trả lời của giám khảo RAGAS được lưu ở `.cache/` (không commit).

## Task 5.1 – Golden Dataset (`golden.jsonl`)

100 câu, biên soạn tay từ **nguyên văn trong kho** (`build_golden.py`); mỗi câu có đáp án chuẩn, căn cứ
(văn bản + Điều [+ Khoản]), `key_facts` (chuỗi bắt buộc có trong câu trả lời đúng: mức tiền, độ tuổi,
số hiệu văn bản thay thế...), `forbidden` (câu chèn lệnh) và `expect_refusal`.

| Lĩnh vực | Số câu | | Loại | Số câu |
|---|---|---|---|---|
| Lao động | 33 | | Câu hỏi sự kiện | 52 |
| Giao thông | 29 | | Cách hỏi đời thường | 25 |
| Hôn nhân và gia đình | 17 | | Ngoài phạm vi (phải từ chối) | 6 |
| Đất đai | 15 | | Tình huống nhiều căn cứ | 4 |
| Ngoài phạm vi | 6 | | Theo mốc thời gian | 4 |
| | | | **Bẫy luật hết hiệu lực** | 4 |
| | | | So sánh cũ – mới | 3 |
| | | | Chèn lệnh (prompt injection) | 2 |

Độ khó: 40 dễ, 42 trung bình, 18 khó. `check_golden.py` xác nhận cả 106 căn cứ đều có đoạn tương ứng
trong kho. Các `key_fact` không tìm thấy nguyên văn đều do lỗi OCR trong kho ("tuôi", "tiên lương")
hoặc là số hiệu văn bản thay thế chỉ có trong đáp án.

## Task 5.2 – Kết quả

### Truy xuất (100 câu, không cần LLM)

"Đoạn đúng" = đoạn thuộc một căn cứ của câu hỏi. **Context Precision@5** theo công thức của RAGAS
(Σ Precision@k × v_k / số đoạn đúng) nhưng xác định đoạn đúng bằng mã điều luật thay vì nhờ LLM chấm –
chính xác hơn và chạy được trên cả bộ dữ liệu để dò tham số.

| Cấu hình | CP@5 | Recall@5 | Hit@1 | MRR |
|---|---|---|---|---|
| Chỉ từ khóa | 0,248 | 0,309 | 0,213 | 0,251 |
| Hybrid, từ khóa ×2 | 0,398 | 0,564 | 0,277 | 0,398 |
| Hybrid ×1 (cấu hình cũ, không rerank) | 0,458 | 0,644 | 0,330 | 0,466 |
| Hybrid, từ khóa ×0,5 | 0,493 | 0,681 | 0,362 | 0,499 |
| Hybrid, từ khóa ×0,25 | 0,588 | 0,771 | 0,457 | 0,591 |
| Chỉ vector | 0,695 | 0,846 | 0,585 | 0,698 |
| Hybrid ×1 + rerank 10 (**cấu hình cũ của hệ thống**) | 0,681 | 0,771 | 0,628 | 0,685 |
| Hybrid ×1 + rerank 20 | 0,742 | 0,867 | 0,670 | 0,749 |
| Hybrid ×0,25 + rerank 10 | 0,744 | 0,851 | 0,670 | 0,750 |
| Chỉ vector + rerank 10 | 0,759 | 0,878 | 0,681 | 0,767 |
| **Hybrid ×0,25 + rerank 20 (đã chọn)** | **0,775** | **0,894** | **0,691** | **0,777** |

Kết luận và thay đổi đã áp dụng:

1. **Luồng từ khóa kéo chất lượng xuống**: văn bản OCR nhiều lỗi dấu, và tiếng Việt viết theo âm tiết
   nên truy vấn "OR từng âm tiết" khớp hàng trăm đoạn ("xe", "máy", "phạt"...). Giảm trọng số từ 1
   xuống **0,25** (`SearchWeights.keyword`) – vẫn giữ để bắt số hiệu văn bản, thuật ngữ chính xác.
   (Thử khớp cụm hai âm tiết bằng `<->` của PostgreSQL: Hybrid ×1 tăng 0,458 → 0,537, chưa bằng giảm
   trọng số nên chưa áp dụng.)
2. **Reranker là bước quan trọng nhất** (+0,19 với cùng ứng viên). Rerank 20 ứng viên tốt hơn 10
   (0,775 so với 0,744) nhưng gấp đôi thời gian trên CPU (~16 s so với ~8 s mỗi câu):
   `RERANK_CANDIDATES=20` mặc định, đặt 10 khi cần nhanh.
3. **Lỗi Router** do bộ dữ liệu phát hiện: câu bắt đầu bằng "Năm 2023, ..." không được nhận là hỏi
   theo mốc thời gian nên trả lời theo luật hiện hành – đã sửa (`router.py`, có test).
4. Ngưỡng từ chối trước khi gọi LLM (`rerank < 0,2`): chặn **6/6** câu ngoài phạm vi, chặn nhầm
   4/94 câu trả lời được.

Context Precision@5 theo loại câu hỏi (cấu hình cũ → đã chọn): sự kiện 0,76 → 0,87; đời thường
0,56 → 0,64; mốc thời gian 0,50 → 0,90; so sánh 0,72 → 0,68; bẫy luật hết hiệu lực 0,50 → 0,55;
nhiều căn cứ 0,57 → 0,58.

### Câu trả lời

Chỉ số tự động (không cần LLM): **đúng dữ kiện** = câu trả lời có đủ mọi `key_fact`; trích dẫn
precision/recall theo căn cứ; từ chối đúng/nhầm; chống chèn lệnh = không chứa `forbidden`.

| Chỉ số | Cấu hình cũ (`answers.jsonl`) | Sau tinh chỉnh (`answers_tuned.jsonl`) |
|---|---|---|
| Đúng dữ kiện (trên câu đã trả lời) | 93,5% | **94,0%** |
| Trích dẫn đúng căn cứ – precision | 82,8% | 79,1% |
| Trích dẫn đúng căn cứ – recall | 90,3% | **96,4%** |
| Từ chối nhầm câu trả lời được | 18,1% (17/94) | **11,7% (11/94)** |
| Từ chối đúng câu ngoài phạm vi | 6/6 | 6/6 |
| Chống chèn lệnh | 2/2 | 2/2 (cả hai bị từ chối) |
| Câu bẫy luật hết hiệu lực – đúng dữ kiện | 67% | **100%** |
| Mô hình sinh | `gemini-flash-lite-latest` | `gemini-3.1-flash-lite` (73 câu), `gemini-3-flash-preview` (17 câu) |
| Cấu hình truy xuất | Hybrid ×1, rerank 10 | Hybrid ×0,25, rerank 20, Router đã sửa |

> Hai lượt dùng mô hình sinh khác nhau (mô hình của lượt đầu hết quota miễn phí trong ngày), nên
> chênh lệch ở bảng trên đến từ cả cấu hình truy xuất lẫn mô hình. Chênh lệch do truy xuất được đo
> riêng ở bảng truy xuất phía trên.

**RAGAS** (`ragas` 0.4.4, giám khảo `gemini-flash-lite-latest`, embedding bge-m3 cho Answer
Relevancy), trên **60/77 câu** đã trả lời của lượt cấu hình cũ – giám khảo hết quota miễn phí trong
ngày trước khi chấm xong (chạy lại lệnh `ragas` để chấm nốt):

| Chỉ số | Kết quả |
|---|---|
| Faithfulness | **0,923** (trung bình), 51/60 câu ≥ 0,8 |
| Answer Relevancy | **0,878** (trung vị 0,905) |

Trước khi chấm, các dòng cảnh báo hiệu lực ⚠️ do hệ thống tự gắn (dựa trên metadata, không do LLM
viết) được bỏ khỏi câu trả lời.

### Phân tích lỗi

- **Từ chối nhầm** gần như luôn do **truy xuất trượt**: đoạn đúng không có trong Top 5 (VD "cầm điện
  thoại khi lái xe máy" lấy Điều 18 thay vì Điều 7 NĐ 168/2024). Khi đó LLM từ chối – đúng thiết kế
  chống ảo giác (thà từ chối còn hơn bịa). Cải thiện truy xuất trực tiếp giảm tỷ lệ này.
- **Lệch phạm vi** (GD-054): "Có những hình thức kỷ luật lao động nào?" trượt Điều 124 BLLĐ; LLM trả
  lời bằng quy định riêng cho lao động giúp việc gia đình (Điều 89 NĐ 145/2020). Chỉ số tự động vẫn
  tính đúng (có đủ "Khiển trách", "Sa thải") nhưng RAGAS Faithfulness = 0 – cần cả hai loại chỉ số.
- **Câu nhiều căn cứ** yếu nhất (đúng dữ kiện 50% ở cả hai lượt): một lượt truy xuất khó lấy đủ cả
  luật lẫn nghị định xử phạt. Câu bẫy luật hết hiệu lực tăng từ 67% lên 100% sau khi sửa Router và
  tinh chỉnh truy xuất.
- Precision trích dẫn giảm nhẹ (82,8% → 79,1%) vì câu trả lời sau tinh chỉnh dẫn nhiều thẻ hơn (232 so
  với 181): phần thêm là nghị định hướng dẫn (chủ yếu 145/2020/NĐ-CP) và Điều/Khoản lân cận trong
  cùng văn bản. Các thẻ này đều đã được xác minh khớp một đoạn trong ngữ cảnh, nhưng không nằm trong
  danh sách căn cứ chuẩn của bộ dữ liệu.
- **Faithfulness thấp** ở một số câu đúng (VD GD-039, GD-044) do giám khảo chặt với nhận định khái
  quát hoặc trích dẫn nghị định hướng dẫn thay vì luật – độ nhiễu của LLM giám khảo.

### Giới hạn của đánh giá

- **Tự chấm**: giám khảo cùng họ Gemini với mô hình sinh; nên chấm lại bằng mô hình khác (GPT, Claude)
  khi có quota.
- **Chunk size chưa được dò**: đổi kích thước đoạn phải sinh lại embedding cho ~4.800 đoạn (khoảng một
  giờ trên CPU) cho mỗi giá trị; cấu hình hiện tại (tối đa 1.800 ký tự, cắt theo Điều/Khoản) giữ
  nguyên. Script đã sẵn sàng để chạy khi có GPU.
- 100 câu là cỡ mẫu nhỏ: chênh lệch dưới ~0,02 CP@5 (2 câu) không có ý nghĩa thống kê.

## Task 5.3 – Semantic Cache (`calibrate_cache.py`)

Ngưỡng chọn bằng dữ liệu (cosine bge-m3):

| Ngưỡng | Trúng cache (cặp cùng ý) | Cặp khác đáp án bị trùng |
|---|---|---|
| 0,90 | 92% | 0 |
| **0,95 (đã chọn)** | 67% | 0 |
| 0,98 | 42% | 0 |

Cặp khác đáp án giống nhau nhất trong Golden Dataset là 0,897. Nhưng thử thêm các cặp chỉ khác một
chi tiết thì **"Xe máy vượt đèn đỏ" và "Ô tô vượt đèn đỏ" giống nhau 0,957** (mức phạt 4–6 triệu so
với 18–20 triệu) – chỉ dùng ngưỡng sẽ trả nhầm. Vì vậy cache còn đòi hỏi **cùng chữ ký**: cùng các con
số (mức tiền, tốc độ, năm, số hiệu) và cùng các cụm phân biệt (loại xe, nam/nữ, ngày thường/ngày
lễ/ban đêm, loại đất, loại hợp đồng, người lao động/người sử dụng lao động, cũ/so sánh). Chi tiết:
[app/cache/semantic.py](../app/cache/semantic.py).

Trúng cache trả lời trong **~0,1 giây** trên CPU (trung vị 107 ms: embedding câu hỏi + truy vấn phiên
bản kho + `VSIM` của Redis), không gọi LLM – so với 8–20 giây cho một câu trả lời đầy đủ (rerank trên
CPU + LLM). Đạt mục tiêu < 0,5 giây của roadmap.
