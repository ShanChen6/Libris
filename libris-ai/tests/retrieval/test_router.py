from datetime import date

import pytest

from app.retrieval.router import route


def test_default_only_in_force() -> None:
    plan = route("Đi xe máy không gương chiếu hậu bên trái có bị phạt không?")
    assert plan.mode == "current"
    assert plan.statuses == ("ACTIVE", "AMENDED")
    assert plan.period is None and plan.referenced == [] and plan.named == []


@pytest.mark.parametrize(
    "query",
    [
        "So sánh mức phạt nồng độ cồn cũ và mới",
        "Quy định cũ về thử việc khác gì hiện nay?",
        "Luật đất đai trước đây quy định thế nào về sổ đỏ",
        "Nghị định này còn hiệu lực không",
    ],
)
def test_compare_includes_expired(query: str) -> None:
    plan = route(query)
    assert plan.mode == "compare"
    assert "EXPIRED" in plan.statuses


def test_document_numbers_are_referenced() -> None:
    plan = route("So sánh Nghị định 100/2019/NĐ-CP và 168/2024/nđ-cp về vượt đèn đỏ")
    assert plan.referenced == ["100/2019/NĐ-CP", "168/2024/NĐ-CP"]
    assert plan.period is None  # năm trong số hiệu không phải mốc thời gian


@pytest.mark.parametrize(
    ("query", "named"),
    [
        ("Theo Luật Đất đai 2013 thì hạn mức giao đất là bao nhiêu?", ("Luật", "Đất đai", 2013)),
        ("Bộ luật Lao động năm 2012 quy định thử việc", ("Bộ luật", "Lao động", 2012)),
    ],
)
def test_named_documents_with_year(query: str, named: tuple[str, str, int]) -> None:
    plan = route(query)
    assert plan.named == [named]
    assert plan.period is None  # "2013" là tên văn bản, không phải mốc thời gian


@pytest.mark.parametrize(
    ("query", "period"),
    [
        ("Vào năm 2019 vượt đèn đỏ bị phạt bao nhiêu?", (date(2019, 1, 1), date(2019, 12, 31))),
        ("Tại thời điểm ngày 15/6/2024 luật nào áp dụng", (date(2024, 6, 15), date(2024, 6, 15))),
        ("vào ngày 1 tháng 8 năm 2024 thì sao", (date(2024, 8, 1), date(2024, 8, 1))),
        ("Trước ngày 1/1/2025 không đội mũ bảo hiểm", (date(2024, 12, 31), date(2024, 12, 31))),
        ("Sau ngày 31/12/2024 thì phạt bao nhiêu", (date(2025, 1, 1), date(2025, 1, 1))),
        # Năm ở đầu câu / đầu vế (lỗi phát hiện bằng Golden Dataset)
        (
            "Năm 2023 đi xe máy không đội mũ bảo hiểm bị phạt bao nhiêu?",
            (date(2023, 1, 1), date(2023, 12, 31)),
        ),
        (
            "Cho hỏi, năm 2020 thời hạn giao đất nông nghiệp là bao lâu?",
            (date(2020, 1, 1), date(2020, 12, 31)),
        ),
    ],
)
def test_point_in_time(query: str, period: tuple[date, date]) -> None:
    plan = route(query)
    assert plan.mode == "point_in_time"
    assert plan.period == period


def test_year_inside_text_is_not_a_period() -> None:
    assert route("Bộ luật Lao động năm 2019 quy định thử việc thế nào?").period is None
    assert route("Phạt từ 400.000 đồng, áp dụng từ 2025").period is None


def test_invalid_date_is_ignored() -> None:
    assert route("vào ngày 31/02/2024 thì sao").period is None


def test_pending() -> None:
    assert "PENDING" in route("Quy định nào sắp có hiệu lực về đất đai?").statuses


@pytest.mark.parametrize(
    ("query", "core"),
    [
        ("So sánh mức phạt khi điều khiển xe máy có nồng độ cồn theo quy định cũ và mới",
         "mức phạt khi điều khiển xe máy có nồng độ cồn"),
        ("Mức phạt không đội mũ bảo hiểm thay đổi thế nào so với trước đây",
         "Mức phạt không đội mũ bảo hiểm thế nào"),
        ("Luật đất đai trước đây quy định thế nào về sổ đỏ",
         "Luật đất đai quy định thế nào về sổ đỏ"),
        ("Thời gian thử việc tối đa", "Thời gian thử việc tối đa"),
        ("so sánh", "so sánh"),  # quá ngắn sau khi bỏ -> giữ nguyên
    ],
)  # fmt: skip
def test_core_question(query: str, core: str) -> None:
    from app.retrieval.router import core_question

    assert core_question(query) == core
