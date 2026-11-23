import unicodedata

from crawler.clean import clean_text, is_colophon_page, strip_continuation_header

RAW = """\
Ký bởi: Cổng Thông tin điện tử Chính phủ
Email: thongtinchinhphu@chinhphu.vn
Thời gian ký: 12.12.2019 16:29:24 +07:00
76
CÔNG BÁO/Số 977 + 978/Ngày 24-8-2024
QUỐC HỘI
Luật số: 36/2024/QH15
Chương I
NHỮNG QUY ĐỊNH
CHUNG
Điều 1. Phạm vi điều chỉnh
Luật này quy định về quy tắc, phương tiện, người tham gia giao thông đường
bộ, chỉ huy, điều khiển giao thông đường bộ.
Điều 2. Giải thích từ ngữ dài được
xuống dòng
1. Người điều khiển phương tiện bao gồm:
người điều khiển xe cơ giới, người điều khiển xe thô sơ.
Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ
2. Các xe qua phà theo thứ tự sau đây:
a) Xe ưu tiên; |
b) Xe chở thư báo.
_ Điều 3. Nguyên tắc ¬
"""


def test_clean_text_structure() -> None:
    assert clean_text(RAW).split("\n") == [
        "QUỐC HỘI",
        "Luật số: 36/2024/QH15",
        "Chương I",
        "NHỮNG QUY ĐỊNH CHUNG",
        "Điều 1. Phạm vi điều chỉnh",
        "Luật này quy định về quy tắc, phương tiện, người tham gia giao thông đường "
        "bộ, chỉ huy, điều khiển giao thông đường bộ.",
        "Điều 2. Giải thích từ ngữ dài được xuống dòng",
        "1. Người điều khiển phương tiện bao gồm: "
        "người điều khiển xe cơ giới, người điều khiển xe thô sơ.",
        "2. Các xe qua phà theo thứ tự sau đây:",
        "a) Xe ưu tiên;",
        "b) Xe chở thư báo.",
        "Điều 3. Nguyên tắc",
    ]


def test_clean_text_normalizes_unicode() -> None:
    decomposed = unicodedata.normalize("NFD", "Điều 1. Phạm vi")  # dấu tổ hợp
    assert decomposed != "Điều 1. Phạm vi"
    assert clean_text(decomposed) == "Điều 1. Phạm vi"
    assert clean_text("168/2024/NÐ-CP") == "168/2024/NĐ-CP"  # Ð (U+00D0) -> Đ


def test_is_colophon_page() -> None:
    colophon = (
        "VĂN PHÒNG CHÍNH PHỦ XUẤT BẢN\nWebsite: http://congbao.chinhphu.vn\nIn tại: Xí nghiệp"
    )
    assert is_colophon_page(colophon)
    assert not is_colophon_page("Điều 5. Quy định\nIn tại: congbao.chinhphu.vn")
    assert not is_colophon_page("Điều 1. Phạm vi điều chỉnh")


def test_strip_continuation_header() -> None:
    text = (
        "CÔNG BÁO/Số 979 + 980/Ngày 24-8-2024\nVĂN BẢN QUY PHẠM PHÁP LUẬT\n"
        "Luật số 36/2024/QH15\n(Tiếp theo Công báo số 977 + 978)\nChương II\nĐiều 24. A"
    )
    assert strip_continuation_header(text) == "Chương II\nĐiều 24. A"
    assert strip_continuation_header("Chương I\nĐiều 1. A") == "Chương I\nĐiều 1. A"


def test_joins_document_number_broken_across_lines() -> None:
    raw = "Điều 110. Sửa đổi, bổ sung một số điều của Nghị định số 37/2019/NĐ\nCP ngày 07 tháng 5"
    assert clean_text(raw) == (
        "Điều 110. Sửa đổi, bổ sung một số điều của Nghị định số 37/2019/NĐ-CP ngày 07 tháng 5"
    )
    assert clean_text("theo Nghị định số 37/2019/NĐ-\nCP ngày 07") == (
        "theo Nghị định số 37/2019/NĐ-CP ngày 07"
    )
    # Dòng mới là nội dung bình thường thì không nối
    assert (
        clean_text("Luật số: 36/2024/QH15\nCỘNG HÒA XÃ HỘI")
        == "Luật số: 36/2024/QH15\nCỘNG HÒA XÃ HỘI"
    )
