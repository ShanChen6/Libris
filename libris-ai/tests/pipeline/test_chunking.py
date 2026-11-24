from app.pipeline.chunking import build_chunks, document_label, from_roman, parse, to_roman

DOC = "\n".join(
    [
        "CHÍNH PHỦ",
        "Số: 168/2024/NĐ-CP",
        "Căn cứ Luật Tổ chức Chính phủ ngày 18 tháng 02 năm 2025;",
        "Chính phủ ban hành Nghị định quy định xử phạt.",
        "Chương l",  # OCR của "Chương I"
        "NHỮNG QUY ĐỊNH CHUNG",
        "Điều I. Phạm vi điều chỉnh",  # OCR của "Điều 1."
        "Nghị định này quy định về xử phạt.",
        "Chương HI",  # OCR hỏng số -> đánh số theo thứ tự: Chương II
        "HÀNH VI VI PHẠM",
        "Mục 1",
        "VI PHẠM QUY TẮC GIAO THÔNG",
        "Điều 2. Xử phạt người điều khiển xe mô tô",
        "1. Phạt tiền từ 200.000 đồng đến 400.000 đồng đối với hành vi sau đây:",
        "a) Không chấp hành hiệu lệnh của đèn tín hiệu giao thông tại nút giao;",
        "b) Không có gương chiếu hậu bên trái người điều khiển hoặc có nhưng không tác dụng;",
        "c) Dừng xe, đỗ xe trên phần đường xe chạy ở đoạn đường ngoài đô thị.",
        "2. Phạt tiền từ 400.000 đồng đến 600.000 đồng đối với hành vi chạy quá tốc độ.",
        "Chương II và Chương IV Nghị định này là mức phạt đối với cá nhân.",  # câu văn
        "Điều 3. Sửa đổi, bổ sung một số điều của Nghị định số 100/2019/NĐ-CP",
        "1. Sửa đổi Điều 17 như sau:",
        "“Điều 17. Xử phạt hành vi khác",  # trích dẫn, không phải tiêu đề
        "Nội dung được sửa đổi.”.",
        "Điều 5 của Nghị định này áp dụng chung.",  # câu văn, không phải tiêu đề
        "Nơi nhận:",
        "Ban Bí thư Trung ương Đảng;",
        "TM. CHÍNH PHỦ",
        "Mẫu số 01 Quyết định xử phạt vi phạm hành chính",
        "Điều 1. Xử phạt đối với ông/bà ................................................"
        + " có hành vi vi phạm hành chính được quy định tại Nghị định số 168/2024/NĐ-CP."
        + " Nội dung mẫu biểu kéo dài để đủ độ dài phụ lục cần giữ lại khi phân tích.",
    ]
)


def _build(max_chars: int = 2000):
    return build_chunks(
        DOC, document_type="Nghị định", document_number="168/2024/NĐ-CP", title="Quy định...",
        max_chars=max_chars,
    )  # fmt: skip


def test_parse_structure_with_ocr_noise() -> None:
    doc = parse(DOC)
    assert [a.label for a in doc.articles] == ["Điều 1", "Điều 2", "Điều 3"]
    assert doc.report.missing_articles == []
    art1, art2, art3 = doc.articles
    assert art1.chapter == "Chương I: NHỮNG QUY ĐỊNH CHUNG"
    assert art2.chapter == "Chương II: HÀNH VI VI PHẠM"
    assert art2.section == "Mục 1: VI PHẠM QUY TẮC GIAO THÔNG"
    assert [c.label for c in art2.clauses] == ["Khoản 1", "Khoản 2"]
    assert [x for x, _ in art2.clauses[0].points] == ["a", "b", "c"]
    # Câu văn bắt đầu bằng "Chương"/"Điều" và Điều trong ngoặc kép thuộc nội dung Điều trước
    assert any("Chương II và Chương IV" in p.text for p in art2.clauses[1].paras)
    assert any("“Điều 17" in p.text for p in art3.clauses[0].paras)
    assert any("Điều 5 của" in p.text for p in art3.clauses[0].paras)
    # Khối chữ ký bị bỏ, mẫu biểu thành phụ lục riêng
    assert [p.text for p in doc.preamble][0].startswith("Căn cứ")
    assert len(doc.appendices) == 1 and doc.appendices[0][0].startswith("Mẫu số 01")


def test_chunks_point_to_exact_text() -> None:
    for max_chars in (2000, 160, 60):
        chunks, _ = _build(max_chars)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        for c in chunks:
            assert DOC[c.char_start : c.char_end] == c.content
            assert c.context_prefix.startswith("[Văn bản: Nghị định 168/2024/NĐ-CP")
        assert all(a.char_end <= b.char_start for a, b in zip(chunks, chunks[1:], strict=False))
        assert max(len(c.content) for c in chunks) <= max(max_chars, 0) or max_chars < 100


def test_short_articles_are_single_chunks() -> None:
    chunks, _ = _build(2000)
    labels = [(c.article, c.clause, c.point, c.article_title) for c in chunks]
    assert labels[0] == (None, None, None, "Căn cứ ban hành")
    assert (labels[1][0], labels[2][0], labels[3][0]) == ("Điều 1", "Điều 2", "Điều 3")
    assert labels[-1][3].startswith("Mẫu số 01") and chunks[-1].part == "Phụ lục"
    art2 = chunks[2]
    assert "Mục 1: Vi phạm quy tắc giao thông" in art2.context_prefix
    assert "Điều 2: Xử phạt người điều khiển xe mô tô" in art2.context_prefix


def test_long_clause_is_split_by_points_with_lead_in_prefix() -> None:
    chunks, _ = _build(160)
    art2 = [c for c in chunks if c.article == "Điều 2"]
    # Tiêu đề Điều + câu dẫn của Khoản 1 đã dài, nên đứng riêng trước các Điểm
    assert [(c.clause, c.point) for c in art2] == [
        ("Khoản 1", None),
        ("Khoản 1", "Điểm a–b"),
        ("Khoản 1", "Điểm c"),
        ("Khoản 2", None),
    ]
    # Câu dẫn (mức phạt) nằm trong tiền tố của các nhóm Điểm sau
    assert "Khoản 1: 1. Phạt tiền từ 200.000 đồng đến 400.000 đồng" in art2[1].context_prefix
    assert art2[0].content.startswith("Điều 2. Xử phạt")  # tiêu đề Điều gộp vào Khoản đầu


def test_very_long_paragraph_is_split_by_sentence() -> None:
    sentence = "Người điều khiển xe phải chấp hành quy định. "
    text = "Điều 1. Quy định chung\n" + (sentence * 30).rstrip()
    chunks, _ = build_chunks(text, document_type="Luật", document_number="1/2024/QH15",
                             title="Luật Thử nghiệm", max_chars=200)  # fmt: skip
    assert len(chunks) > 5
    assert all(len(c.content) <= 200 for c in chunks)
    assert all(text[c.char_start : c.char_end] == c.content for c in chunks)
    assert chunks[0].content == "Điều 1. Quy định chung"
    assert all(c.content.endswith(".") for c in chunks[1:])  # cắt đúng ranh giới câu


def test_missing_article_is_reported() -> None:
    text = "Điều 1. A\nNội dung.\nĐiều 3. C\nNội dung.\nĐiều 90. Nhảy số do OCR\nNội dung."
    doc = parse(text)
    assert [a.label for a in doc.articles] == ["Điều 1", "Điều 3"]
    assert doc.report.missing_articles == [2]
    assert doc.report.rejected_headings == ["Điều 90. Nhảy số do OCR"]


def test_roman_and_labels() -> None:
    assert [to_roman(n) for n in (1, 4, 9, 14, 40, 90)] == ["I", "IV", "IX", "XIV", "XL", "XC"]
    assert from_roman("XVI") == 16 and from_roman("HI") is None and from_roman("IIII") is None
    assert document_label("Luật", "31/2024/QH15", "Luật Đất đai") == "Luật Đất đai 31/2024/QH15"
    assert (
        document_label("Luật", "43/2024/QH15", "Luật sửa đổi, bổ sung một số điều của Luật Đất đai")
        == "Luật 43/2024/QH15"
    )
    assert document_label("Nghị định", "168/2024/NĐ-CP", "Quy định") == "Nghị định 168/2024/NĐ-CP"


def test_clause_number_misread_by_ocr() -> None:
    # "5." bị OCR đọc thành "%," (NĐ 168/2024, Điều 6): vẫn nhận là Khoản kế tiếp, không gộp vào
    # Khoản trước
    doc = parse(
        "\n".join(
            [
                "Điều 6. Xử phạt người điều khiển xe ô tô",
                "1. Phạt tiền từ 2.000.000 đồng đến 3.000.000 đồng đối với hành vi sau đây:",
                "a) Không giữ khoảng cách an toàn với xe chạy liền trước.",
                "%, Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng đối với hành vi sau đây:",
                "a) Dùng tay cầm và sử dụng điện thoại khi điều khiển phương tiện;",
                # Khoản trước chưa kết thúc bằng dấu chấm: không phải Khoản
                "S, bị phạt nếu tái phạm;",
                "3. Phạt tiền từ 6.000.000 đồng đến 8.000.000 đồng.",
            ]
        )
    )
    clauses = doc.articles[0].clauses
    assert [c.label for c in clauses] == ["Khoản 1", "Khoản 2", "Khoản 3"]
    assert "điện thoại" in clauses[1].paras[1].text and len(clauses[1].paras) == 3
