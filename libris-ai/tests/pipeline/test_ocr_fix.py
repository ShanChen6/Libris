from app.pipeline.ocr_fix import LanguageModel, base, fix_text

CLEAN = (
    ["Người điều khiển xe bị phạt tiền từ 400.000 đồng đến 600.000 đồng. Giấy phép lái xe bị tước."]
    * 20
    + ["a) Tạo điều kiện."] * 20
    + ["Quyền sử dụng đất của người sử dụng đất. Giấy tờ giả bị thu hồi. Giấy phép hết hạn."] * 20
)


def test_base_drops_only_tone_marks() -> None:
    assert base("điều") == base("Điêu") == "điêu"
    assert base("đất") == "đât"
    assert base("dưỡng") != base("đường") and base("mức") != base("mục")


def test_restores_dropped_tone_marks_from_context() -> None:
    lm = LanguageModel.from_texts(CLEAN)
    text = "Người điêu khiên xe bị tước Giây phép lái xe; quyên sử dụng đât."
    fixed, report = fix_text(text, lm)
    assert fixed == "Người điều khiển xe bị tước Giấy phép lái xe; quyền sử dụng đất."
    assert len(fixed) == len(text) and report.replaced == 5


def test_keeps_words_that_fit_their_context_and_numbers() -> None:
    lm = LanguageModel.from_texts(CLEAN)
    # "từ" trước con số là đúng; "giả" đúng trong "giấy tờ giả"; con số không bao giờ bị đổi
    text = "Phạt tiền từ 2.000.000 đồng. Giấy tờ giả bị thu hồi. b) Tảo hôn bị cấm."
    fixed, report = fix_text(text, lm)
    assert fixed == text and report.replaced == 0


from app.pipeline.ocr_fix import (  # noqa: E402
    fix_clause_numbers,
    fix_confusions,
    fix_ocr,
    fix_point_labels,
)

VOCAB = LanguageModel.from_texts(
    ["Ly hôn là việc chấm dứt quan hệ vợ chồng. Thủ tục ly hôn. Yêu cầu ly hôn. Giao thông."] * 3
    + ["Giao kết hợp đồng. Thời gian giao kết. Khoản 8a Điều 24."] * 3
)


def test_fix_confusions() -> None:
    fixed, report = fix_confusions("14. 1y hôn là việc chấm dứt; g1ao kết hợp đồng", VOCAB)
    assert fixed == "14. ly hôn là việc chấm dứt; giao kết hợp đồng"
    assert report.replaced == 2
    # Số hiệu có chữ cái, số La Mã, từ không có ngữ cảnh xác nhận: giữ nguyên
    for text in ("khoản 8a Điều 24", "Mục i1 chương", "abc 1x def"):
        assert fix_confusions(text, VOCAB)[0] == text


def test_fix_point_labels() -> None:
    text = (
        "1. Phạt tiền:\na) Một;\nb) Hai;\n©) Ba;\nđ) Bốn;\nđ) Năm;\ne) Sáu;\n8) Bảy;\nh) Tám;\n"
        "¡) Chín;\nk) Mười;\n1) Mười một;\n2. Khoản khác:\n1) không phải Điểm;\na) Một."
    )
    fixed, report = fix_point_labels(text)
    labels = [line.split(")")[0] for line in fixed.splitlines() if ")" in line]
    assert labels == ["a", "b", "c", "d", "đ", "e", "g", "h", "i", "k", "l", "1", "a"]
    assert len(fixed) == len(text) and report.replaced == 5


def test_point_label_d_kept_when_d_really_missing() -> None:
    text = "1. X:\na) Một;\nb) Hai;\nc) Ba;\nđ) Năm;\n2. Y."
    assert fix_point_labels(text)[0] == text  # có thể Điểm d bị OCR bỏ sót


def test_fix_clause_numbers() -> None:
    text = (
        "Điều 3. Giải thích từ ngữ\n14. Ly hôn là việc chấm dứt.\n"
        "15. Ly hôn giả tạo là việc lợi dụng. l6. Thành viên gia đình gồm vợ, chồng.\n"
        "Điều 4. Khác\nII. Phần La Mã\n"
    )
    fixed, report = fix_clause_numbers(text)
    assert "lợi dụng.\n16. Thành viên" in fixed
    assert "II. Phần La Mã" in fixed and len(fixed) == len(text)
    assert report.replaced == 1


def test_fix_ocr_keeps_length() -> None:
    text = "Điều 3.\n1. X.\n2. 1y hôn là. 3. Y:\na) a;\nb) b;\n©) c"
    fixed, _ = fix_ocr(text, VOCAB)
    assert len(fixed) == len(text)
    assert fixed == "Điều 3.\n1. X.\n2. ly hôn là.\n3. Y:\na) a;\nb) b;\nc) c"
