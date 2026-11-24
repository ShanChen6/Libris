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
| Từ chối nhầm câu trả lời được | 18,1% (17/94) | **11,7% (11/94)** – 17,0% và 9,6% theo cách chấm đã sửa (mục cuối) |
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

## Sau Giai đoạn 5 – Xử lý các điểm yếu đã phát hiện

Các lỗi do bộ dữ liệu chỉ ra và cách xử lý (chi tiết trong README của `app/pipeline`,
`app/retrieval`, `app/generation`):

| Điểm yếu | Xử lý |
|---|---|
| OCR làm mất dấu thanh (~30.000 chỗ: "đât", "điêu", "câm") | `ocr_fix.py`: hiệu đính theo ngữ cảnh hai âm tiết học từ văn bản sạch; ~29.000 chỗ, 40/40 mẫu kiểm tra đúng; cắt đoạn + embedding lại |
| OCR đọc sai số Khoản ("%, Phạt tiền" = "5.") làm cả Khoản bị gộp vào Khoản trước | Bộ cắt đoạn nhận Khoản kế tiếp trong trường hợp này |
| Từ khóa "OR từng âm tiết" khớp hàng nghìn đoạn | Tìm theo **cụm hai âm tiết** (`'đèn' <-> 'tín'`); trọng số từ khóa trở lại 1 (0,25 khi không có reranker) |
| "xe máy" trúng điều khoản "xe máy chuyên dùng", câu đường bộ trúng điều khoản đường sắt | Giảm điểm đoạn thuộc lĩnh vực chuyên biệt khi câu hỏi không nhắc tới |
| Câu nhiều ý ("vừa A vừa B", nhiều vế hỏi) | Tách câu hỏi con, truy xuất riêng, mỗi ý giữ chỗ trong Top 5 |
| Router: "trước **và** sau năm 2025" bị hiểu là "sau năm 2025" | Giữ chế độ so sánh |
| Cách nói đời thường "cầm điện thoại" | Ánh xạ sang "dùng tay cầm và sử dụng điện thoại..."; "vừa" thành hư từ |
| Câu hỏi nối tiếp ("còn ô tô thì sao?") | Ghép với câu hỏi trước trong hội thoại (libris-api gửi kèm lịch sử) |
| Cách chấm: câu chèn lệnh bị từ chối tính là "từ chối nhầm" | Với câu chèn lệnh, từ chối hay trả lời đúng đều đạt; chỉ sai khi nói theo nội dung bị cài |

**Truy xuất** (Hybrid + rerank 20, 100 câu):

| | Cấu hình ban đầu | Sau Giai đoạn 5 | **Sau xử lý điểm yếu** |
|---|---|---|---|
| Context Precision@5 | 0,681 | 0,775 | **0,809** |
| Recall@5 | 0,771 | 0,894 | **0,931** |
| Hit@1 | 0,628 | 0,691 | **0,723** |
| Chặn nhầm ở ngưỡng rerank | 4/94 | 4/94 | **3/94** |

Theo loại câu hỏi (Sau Giai đoạn 5 → hiện tại, CP@5): bẫy luật hết hiệu lực 0,55 → 0,72; sự kiện
0,87 → 0,90; nhiều căn cứ 0,58 → 0,60. Rerank 10 ứng viên (nhanh gấp đôi trên CPU): CP@5 0,757.

**Câu trả lời** (cùng cách chấm đã sửa cho cả ba lượt):

| Chỉ số | `answers.jsonl` (ban đầu) | `answers_tuned.jsonl` (sau GĐ 5) | **`answers_fixed.jsonl` (hiện tại)** |
|---|---|---|---|
| Đúng dữ kiện | 93,5% | 94,0% | **95,5%** |
| Trích dẫn – precision | 82,8% | 79,1% | **82,7%** |
| Trích dẫn – recall | 90,3% | 96,4% | **97,7%** |
| Từ chối nhầm câu trả lời được | 17,0% | 9,6% | **5,3%** |
| Từ chối đúng câu ngoài phạm vi | 6/6 | 6/6 | 6/6 |
| Chống chèn lệnh | 2/2 | 2/2 | 2/2 |
| Câu nhiều căn cứ – đúng dữ kiện | 50% | 50% | **67%** |
| Câu so sánh / mốc thời gian / bẫy luật | 100% / 100% / 67% | 100% / 100% / 100% | 100% / 100% / 100% |
| Mô hình sinh | flash-lite-latest | 3.1-flash-lite (73), 3-flash-preview (17) | 3.1-flash-lite (80), flash-lite-latest (11); 9 câu bị chặn trước khi gọi LLM |

Lượt "hiện tại" so sánh được nhất với lượt "sau GĐ 5" (cùng chủ yếu `gemini-3.1-flash-lite`). Ví dụ
câu trước đây trượt nay đúng: "ô tô vượt đèn đỏ" -> 18–20 triệu `[Điều 6, Khoản 9 - 168/2024/NĐ-CP]`;
"vừa lái xe máy vừa cầm điện thoại" -> `[Điều 7, Khoản 4 - 168/2024/NĐ-CP]`; "trước và sau năm 2025"
-> nêu cả mức cũ 200–300 nghìn lẫn mức mới 400–600 nghìn.

### Vòng 2: kiểm tra độc lập (hold-out) và vá tiếp

Để kiểm tra rủi ro "học thuộc đề", bộ **hold-out** (`holdout.jsonl`, 20 câu, `build_holdout.py`)
được soạn sau khi tinh chỉnh: 12 câu về các Điều chưa có trong Golden Dataset (nghỉ hằng tuần, phép
thâm niên, nghỉ khi kết hôn, lao động nữ mang thai, đăng ký kết hôn, chấm dứt hôn nhân, đăng ký biến
động đất, chở người trên xe máy/xe đạp, tuổi bằng hạng C), 6 cách hỏi mới cho tình huống đã có và 2
câu nhiều ý. Hệ thống cũ (code commit `7c7a074` + dữ liệu sao lưu trước khi hiệu đính OCR) được dựng
lại để so sánh trên cùng bộ câu và cùng mô hình sinh (`gemini-3.1-flash-lite`):

| Hold-out (20 câu) | Hệ thống cũ (sau GĐ 5) | Hiện tại |
|---|---|---|
| Context Precision@5 | **0,892** | 0,842 |
| Recall@5 | 0,950 | 0,950 |
| Hit@1 | **0,850** | 0,750 |
| Đúng dữ kiện (câu đã trả lời) | 94,1% (16/17) | **100%** (18/18) |
| Từ chối nhầm | 15% (3/20) | **10%** (2/20) |

Kết luận trung thực: **xếp hạng** của hệ thống hiện tại kém hệ thống cũ trên câu hỏi mới (đúng dấu
hiệu "học thuộc đề" đã cảnh báo), nhưng **câu trả lời** đúng hơn và ít từ chối nhầm hơn vì đoạn đúng
vẫn nằm trong Top 5. Phân tích từng câu dẫn tới các bản vá:

| Phát hiện trên hold-out | Xử lý |
|---|---|
| "chạy **xe máy** nhắn tin điện thoại": Điều 6 (**ô tô**) xếp trên Điều 7 | Giảm điểm đoạn có loại xe (theo tên Điều) khác với câu hỏi |
| "mang bầu", "đặt cọc": đoạn đúng đứng số 1 nhưng điểm rerank 0,021 / 0,014 < ngưỡng 0,2 nên bị **chặn trước LLM** (ở cả hệ thống cũ) | Ngưỡng 0,2 -> **0,05**: trên 120 câu, câu ngoài phạm vi cao nhất 0,013; chặn nhầm 5 -> 2/114, vẫn chặn đủ 6/6. Ánh xạ "mang bầu" -> "mang thai", "đặt cọc" -> "biện pháp bảo đảm bằng tiền" |
| GD-100 "muốn ly hôn **và** giành quyền nuôi con" | Tách khi có động từ tình thái ("muốn", "định"...) + "A và B" + phần hỏi; "nam và nữ" không bị tách |
| Bộ chấm: "không có căn cứ để khẳng định nữ đủ 16 tuổi là được kết hôn" bị tính là nói theo nội dung cài | Bỏ qua lần xuất hiện trong câu phủ định |
| GD-012: LLM chọn Khoản "chở từ 03 người" thay cho "chở 02 người" dù ngữ cảnh có Khoản đúng | Thêm quy tắc prompt đối chiếu con số/điều kiện; chạy lặp lại 3 lần: đúng 2/3 – vẫn còn ngẫu nhiên với mô hình nhẹ |
| Thử thêm: truy vấn từ khóa = cụm hai âm tiết + từng âm tiết | **Không áp dụng**: kém hơn trên cả hai bộ (0,744 / 0,842 so với 0,803 / 0,867) |

**Kết quả cuối** (toàn bộ câu trả lời sinh lại bằng code hiện tại: `answers_current.jsonl`,
`answers_holdout_current.jsonl`; `gemini-3.1-flash-lite`):

| | Golden Dataset (100) | Hold-out (20) |
|---|---|---|
| Context Precision@5 / Recall@5 / Hit@1 | 0,803 / 0,936 / 0,713 | 0,842 / 0,950 / 0,750 |
| Đúng dữ kiện | 94,4% | 100% |
| Trích dẫn – precision / recall | 81,6% / 96,1% | 91,4% / 97,2% |
| Từ chối nhầm | **4,3%** | 10% |
| Từ chối đúng câu ngoài phạm vi / chống chèn lệnh | 6/6 / 2/2 | – |
| Câu nhiều căn cứ | **75%** | 100% (2/2) |

**Lưu ý về cách đọc số liệu:** sau vòng 2, bộ hold-out cũng đã được dùng để tìm lỗi (loại xe, ngưỡng,
"mang bầu", "đặt cọc") nên không còn hoàn toàn độc lập. Muốn ước lượng không thiên lệch cần một bộ
câu hỏi mới nữa, tốt nhất do người khác soạn.

**Còn lại:**

- HO-008 "Ly hôn là gì": OCR ghi "**1y** hôn" (số 1 thay chữ l) nên tìm theo cụm không khớp
  (đã xử lý ở vòng 3).
- HO-016: Khoản 8 và 9 (nồng độ cồn) đều chứa "0,4", reranker khó phân biệt.
- LLM nhẹ đôi khi chọn nhầm Khoản giữa các điều kiện chỉ khác con số (GD-012).
- RAGAS chưa chấm lại cho lượt hiện tại: giám khảo cũ (`gemini-flash-lite-latest`) hết quota; đổi
  giám khảo thì điểm không so sánh được với lần chấm trước.

### Vòng 3: xử lý tận gốc các điểm còn lại

| Vấn đề | Cách xử lý | Kết quả |
|---|---|---|
| LLM chọn nhầm Khoản chỉ khác con số (GD-012, HO-016) | **Lớp kiểm tra thứ 4** (`app/generation/verify.py`): điều kiện có đơn vị trong câu hỏi (số người chở theo, km/h, nồng độ cồn, tuổi) đổi thành khoảng giá trị và đối chiếu với Điểm/Khoản được dẫn; số tiền trong câu phải có trong Khoản được dẫn. Sai -> mô hình viết lại một lần với gợi ý cụ thể. `temperature` 0,1 -> 0 | Chạy lại trên ~290 câu trả lời đã lưu: bắt đúng lỗi GD-012, **không báo nhầm câu nào** |
| HO-008 "1y hôn" và lỗi mặt chữ khác của OCR | `fix_confusions` (ký tự nhầm trong từ), `fix_point_labels` (~440 nhãn Điểm "©)" "8)" "¡)"), `fix_clause_numbers` (số Khoản dính dòng) | Hold-out CP@5 0,842 -> 0,871, Hit@1 0,75 -> 0,85 |
| HO-008 vẫn trượt: đoạn định nghĩa không vào được 20 ứng viên | Luồng tìm thứ tư cho câu hỏi định nghĩa ("X là gì", "thế nào là X"): dòng "N. X là ..." | Khoản 14 Điều 3 đứng đầu (rerank 0,996); hold-out CP@5 0,871 -> **0,917**, Recall@5 **1,0**, Hit@1 **0,90** |
| Câu hỏi đời thường khác xa từ ngữ của luật (GD-041 "nghỉ ngang", GD-053, GD-063, GD-073): Điều đúng không lọt vào 20 ứng viên | Thử nghiệm `app/retrieval/rewrite.py`: LLM viết lại câu hỏi bằng thuật ngữ pháp lý, tìm bằng cả câu gốc lẫn câu viết lại rồi gộp ứng viên (cấu hình `hybrid_kw1_rerank20_rewrite`) | **Không bật.** Hold-out giữ nguyên (0,917 / 1,0 / 0,90); Golden CP@5 0,803 -> 0,800, Recall@5 0,936 -> 0,941, Hit@1 0,713 -> 0,702 (GD-035 tìm thêm được 1 Điều, GD-011 mất vị trí đầu); 4 câu mục tiêu vẫn trượt; mỗi câu tốn thêm một lần gọi LLM. Bộ tự động chưa chạy xong vì hết quota Gemini |
| Bộ đánh giá nhỏ, do người soạn và đã dùng khi tinh chỉnh | **Bộ 152 câu sinh tự động** (`build_synthetic.py`, `synthetic.jsonl`): mỗi câu viết từ một đoạn luật còn hiệu lực ngẫu nhiên, **không trùng Điều** với Golden/hold-out; bỏ NĐ 100/2019 và các Điều/Khoản đã bị bãi bỏ (đáp án sẽ là văn bản thay thế) | Xem bảng dưới |

**Bộ 152 câu tự động** (mức trùng cặp từ với văn bản ~0,32, tức phần lớn đã được diễn đạt lại):

| Cấu hình | CP@5 | Recall@5 | Hit@1 |
|---|---|---|---|
| Lai + rerank 20 (**cấu hình đang dùng**) | **0,778** | **0,901** | **0,697** |
| Chỉ vector | 0,716 | 0,882 | 0,612 |
| Lai, từ khóa ×0,25, không rerank | 0,535 | 0,783 | 0,395 |

- Cấu hình đang dùng **giữ được chất lượng trên câu hỏi chưa từng thấy** (0,778 so với 0,803 trên
  Golden Dataset); chỉ 1,3% câu bị chặn nhầm trước LLM.
- Phát hiện lỗi cấu hình: khi **tắt reranker**, hệ thống dùng lai từ khóa ×0,25 – trọng số này từng
  được chọn vì tốt hơn ×1, nhưng chưa bao giờ so với vector thuần. Vector thuần tốt hơn trên cả ba bộ
  (CP@5 / Hit@1: Golden 0,686/0,574 vs 0,674/0,543; hold-out 0,710/0,650 vs 0,675/0,550; tự động
  0,716/0,612 vs 0,535/0,395) -> chế độ không reranker chuyển sang **chỉ vector** (vẫn giữ luồng văn
  bản được nêu tên và luồng định nghĩa).

| Cấu hình đang dùng | Golden (100) | Hold-out (20) | Tự động (152) |
|---|---|---|---|
| CP@5 / Recall@5 / Hit@1 | 0,803 / 0,936 / 0,713 | 0,917 / 1,000 / 0,900 | 0,778 / 0,901 / 0,697 |

Giới hạn của bộ tự động: câu hỏi do LLM viết từ chính đoạn luật nên dễ hơn câu hỏi thật ở chỗ dùng
lại từ ngữ, nhưng khó hơn ở chỗ đôi khi nhiều đoạn khác cũng trả lời được (bị chấm sai dù hệ thống
đúng). Bộ chỉ dùng để đo, không dùng để tinh chỉnh. Chưa sinh lại câu trả lời cho vòng này: hết quota
Gemini gói miễn phí trong ngày (lớp kiểm tra thứ 4 đã được kiểm chứng bằng test và chạy lại trên các
câu trả lời đã lưu).

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
