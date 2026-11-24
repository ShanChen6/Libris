from app.retrieval.decompose import sub_questions
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)


def test_both_behaviours_are_split() -> None:
    assert sub_questions(
        "Đi xe máy vừa không đội mũ bảo hiểm vừa vượt đèn đỏ thì bị phạt những khoản nào?"
    ) == [
        "Đi xe máy không đội mũ bảo hiểm thì bị phạt những khoản nào?",
        "Đi xe máy vượt đèn đỏ thì bị phạt những khoản nào?",
    ]


def test_several_questions_keep_their_context() -> None:
    q = (
        "Công ty bắt tôi thử việc 90 ngày cho vị trí kế toán. "
        "Như vậy có đúng luật không, công ty bị phạt thế nào?"
    )
    assert sub_questions(q) == [
        "Công ty bắt tôi thử việc 90 ngày cho vị trí kế toán. Như vậy có đúng luật không",
        "Công ty bắt tôi thử việc 90 ngày cho vị trí kế toán. công ty bị phạt thế nào?",
    ]


def test_later_questions_without_context_keep_the_first_one() -> None:
    assert sub_questions("Chở 3 người bị phạt bao nhiêu? Có trường hợp nào được chở không?") == [
        "Chở 3 người bị phạt bao nhiêu?",
        "Chở 3 người bị phạt bao nhiêu? Có trường hợp nào được chở không?",
    ]


def test_two_wanted_actions_are_split() -> None:
    assert sub_questions(
        "Vợ tôi đang nuôi con 10 tháng tuổi. Tôi muốn ly hôn và giành quyền nuôi con được không?"
    ) == [
        "Vợ tôi đang nuôi con 10 tháng tuổi. Tôi muốn ly hôn được không?",
        "Vợ tôi đang nuôi con 10 tháng tuổi. Tôi muốn giành quyền nuôi con được không?",
    ]


def test_leading_conjunction_is_dropped() -> None:
    # Không có câu bối cảnh riêng: vế đầu được ghép vào vế sau
    assert sub_questions("Nghỉ việc báo trước bao lâu, và trợ cấp thôi việc tính thế nào?") == [
        "Nghỉ việc báo trước bao lâu",
        "Nghỉ việc báo trước bao lâu trợ cấp thôi việc tính thế nào?",
    ]


def test_single_question_is_unchanged() -> None:
    for q in [
        "Không đội mũ bảo hiểm khi đi xe máy bị phạt bao nhiêu tiền?",
        "Thời gian thử việc tối đa, theo Bộ luật Lao động 2019, là bao lâu?",
        "Vợ tôi đang nuôi con 10 tháng tuổi. Tôi muốn ly hôn được không?",
        "Tuổi kết hôn của nam và nữ là bao nhiêu?",
        "Nam và nữ có quyền bình đẳng trong hôn nhân không?",
        # Một hành vi: lái xe là hoạt động nền (GD-004 bị tách nhầm ở phiên bản đầu)
        "Vừa lái xe máy vừa cầm điện thoại nghe gọi thì bị phạt thế nào?",
    ]:
        assert sub_questions(q) == [q]


def test_retrieve_finds_a_basis_for_each_part(seeded) -> None:  # noqa: F811
    import psycopg

    from app.retrieval.service import retrieve
    from tests.fakes import FakeReranker

    conninfo, emb = seeded
    q = "xe mô tô vừa không có gương chiếu hậu bên trái vừa vượt đèn đỏ thì bị phạt bao nhiêu"
    with psycopg.connect(conninfo) as conn:
        res = retrieve(conn, q, emb, FakeReranker(), candidates=10, top_n=2)
    contents = " ".join(h.content for h in res.hits)
    assert "gương chiếu hậu" in contents and "đèn đỏ" in contents
    assert " | " in res.expanded_query  # hai câu hỏi con
