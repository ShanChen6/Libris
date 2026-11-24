from app.pipeline.ocr_fix import LanguageModel, base, fix_text

CLEAN = [
    "Người điều khiển xe bị phạt tiền từ 400.000 đồng đến 600.000 đồng. Giấy phép lái xe bị tước."
] * 20 + [
    "Quyền sử dụng đất của người sử dụng đất. Giấy tờ giả bị thu hồi. Giấy phép hết hạn."
] * 20


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
    text = "Phạt tiền từ 2.000.000 đồng. Giấy tờ giả bị thu hồi."
    fixed, report = fix_text(text, lm)
    assert fixed == text and report.replaced == 0
