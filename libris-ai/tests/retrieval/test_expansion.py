from app.retrieval.expansion import expand_query
from app.retrieval.router import route


def test_expands_colloquial_terms() -> None:
    q = "Vượt đèn đỏ bằng xe máy bị phạt bao nhiêu?"
    out = expand_query(q)
    assert out.startswith(q)
    assert "không chấp hành hiệu lệnh của đèn tín hiệu giao thông" in out
    assert "xe mô tô xe gắn máy" in out


def test_no_expansion_when_nothing_matches_or_already_legal() -> None:
    assert expand_query("Thời gian thử việc tối đa là bao lâu?") == (
        "Thời gian thử việc tối đa là bao lâu?"
    )
    q = "Không chấp hành hiệu lệnh của đèn tín hiệu giao thông"
    assert expand_query(q) == q


def test_whole_words_only() -> None:
    # "cưới" là từ, nhưng không khớp bên trong từ khác
    assert "kết hôn" in expand_query("Đăng ký cưới cần gì")
    assert expand_query("tiền nhậu") != expand_query("tiền nhậuu")


def test_expansion_does_not_change_routing() -> None:
    q = "Vượt đèn đỏ bị phạt bao nhiêu?"
    assert route(expand_query(q)).mode == route(q).mode == "current"
