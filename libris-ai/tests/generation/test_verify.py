import math
from datetime import date

import pytest

from app.generation import answer as answer_mod
from app.generation.answer import Prepared, answer_question, stream_answer
from app.generation.verify import amounts, check_answer, conditions
from app.retrieval.router import RetrievalPlan
from tests.fakes import FakeLLM
from tests.generation.test_citations_prompt import hit

K2 = hit(
    clause="Khoản 2",
    content="2. Phạt tiền từ 400.000 đồng đến 600.000 đồng đối với người điều khiển xe:\n"
    "a) Dừng xe trên phần đường xe chạy;\n"
    "g) Chở theo 02 người trên xe, trừ trường hợp chở người bệnh đi cấp cứu;",
)
K3_HEAD = hit(
    clause="Khoản 3",
    point="Điểm a–h",
    content="3. Phạt tiền từ 600.000 đồng đến 800.000 đồng đối với người điều khiển xe:\n"
    "a) Chuyển hướng không quan sát;\nb) Chở theo từ 03 người trở lên trên xe;",
)
K3_TAIL = hit(clause="Khoản 3", point="Điểm k", content="k) Chạy dàn hàng ngang từ 03 xe trở lên;")
K8 = hit(
    clause="Khoản 8",
    content="8. Phạt tiền từ 6.000.000 đồng đến 8.000.000 đồng:\nb) Điều khiển xe mà có nồng độ "
    "cồn vượt quá 50 miligam đến 80 miligam/100 mililít máu hoặc vượt quá 0,25 miligam đến 0,4 "
    "miligam/1 lít khí thở.",
)
K9 = hit(
    clause="Khoản 9",
    content="9. Phạt tiền từ 8.000.000 đồng đến 10.000.000 đồng:\nd) Điều khiển xe mà có nồng độ "
    "cồn vượt . quá 80 miligam/100 mililít máu hoặc vượt quá 0,4 miligam/1 lít khí thở;",
)
HITS = [K2, K3_HEAD, K3_TAIL, K8, K9]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("chở theo 2 người (cả xe 3 người)", [("người chở theo", 2, 2, True, True)]),
        ("Chở theo từ 03 người trở lên", [("người chở theo", 3, math.inf, True, False)]),
        ("được chở tối đa hai người", [("người chở theo", 0, 2, True, True)]),
        ("đo ra vượt 0,4 miligam/lít khí thở", [("mg/l khí thở", 0.4, math.inf, False, False)]),
        (
            "vượt quá 50 miligam đến 80 miligam/100 mililít máu",
            [("mg/100ml máu", 50, 80, False, True)],
        ),
        ("quá tốc độ từ 05 km/⁄h đến dưới 10 km/h", [("km/h", 5, 10, True, False)]),
        ("trẻ em dưới 12 tuổi", [("tuổi", -math.inf, 12, False, False)]),
        ("phạt 400.000 đồng, Điều 7 năm 2024", []),
    ],
)
def test_conditions(text, expected) -> None:
    got = [(c.unit, c.lo, c.hi, c.lo_incl, c.hi_incl) for c in conditions(text)]
    assert got == expected


def test_amounts() -> None:
    assert amounts("phạt 18 – 20 triệu đồng hoặc từ 400.000 đồng đến 600.000 đồng") == {
        18e6, 20e6, 4e5, 6e5,
    }  # fmt: skip
    assert amounts("Điều 7 có 02 người") == set()


def test_wrong_clause_by_condition() -> None:
    q = "Đi xe máy chở theo 2 người bị phạt bao nhiêu?"
    wrong = "Phạt từ 600.000 đến 800.000 đồng [Điều 7, Khoản 3, Điểm b - 168/2024/NĐ-CP]."
    found = check_answer(q, wrong, HITS)
    assert len(found) == 1
    assert "03 người" in found[0].reason and "Khoản 2" in found[0].suggestion
    right = "Phạt từ 400.000 đến 600.000 đồng [Điều 7, Khoản 2, Điểm g - 168/2024/NĐ-CP]."
    assert check_answer(q, right, HITS) == []


def test_wrong_clause_by_alcohol_range() -> None:
    q = "Đo ra vượt 0,4 miligam/lít khí thở thì phạt bao nhiêu?"
    assert check_answer(q, "Phạt 6 – 8 triệu đồng [Điều 7, Khoản 8 - 168/2024/NĐ-CP].", HITS)
    assert not check_answer(q, "Phạt 8 – 10 triệu đồng [Điều 7, Khoản 9 - 168/2024/NĐ-CP].", HITS)


def test_contrast_with_other_clause_is_not_flagged() -> None:
    q = "Đo ra vượt 0,4 miligam/lít khí thở thì phạt bao nhiêu?"
    answer = (
        "Phạt 8 – 10 triệu đồng [Điều 7, Khoản 9 - 168/2024/NĐ-CP]. Mức thấp hơn (0,25 đến 0,4) "
        "bị phạt 6 – 8 triệu đồng [Điều 7, Khoản 8 - 168/2024/NĐ-CP]."
    )
    assert check_answer(q, answer, HITS) == []


def test_wrong_clause_by_amount() -> None:
    q = "Không đội mũ bảo hiểm bị phạt bao nhiêu?"
    wrong = "Bị phạt từ 400.000 đồng đến 600.000 đồng [Điều 7, Khoản 3 - 168/2024/NĐ-CP]."
    found = check_answer(q, wrong, HITS)
    assert len(found) == 1 and "400.000" in found[0].reason
    # Khoản dài bị chia đoạn: mức phạt ở đoạn đầu vẫn được tính cho đoạn sau
    tail = "Phạt 600.000 – 800.000 đồng [Điều 7, Khoản 3, Điểm k - 168/2024/NĐ-CP]."
    assert check_answer("Chạy hàng ngang bị phạt?", tail, HITS) == []


def test_no_alternative_means_no_flag() -> None:
    # Không có đoạn nào khớp điều kiện -> không đủ căn cứ để nói là dẫn nhầm
    q = "Chở theo 5 người bị phạt bao nhiêu?"
    answer = "Phạt 600.000 – 800.000 đồng [Điều 7, Khoản 3, Điểm b - 168/2024/NĐ-CP]."
    assert check_answer(q, answer, [K2, K3_HEAD]) == []


WRONG = "Phạt từ 600.000 đến 800.000 đồng [Điều 7, Khoản 3, Điểm b - 168/2024/NĐ-CP]."
RIGHT = "Phạt từ 400.000 đến 600.000 đồng [Điều 7, Khoản 2, Điểm g - 168/2024/NĐ-CP]."
QUESTION = "Đi xe máy chở theo 2 người bị phạt bao nhiêu?"


@pytest.fixture
def prepared(monkeypatch):
    prep = Prepared(QUESTION, RetrievalPlan(), HITS, date(2025, 6, 1), {})
    monkeypatch.setattr(answer_mod, "prepare", lambda *a, **kw: prep)


def _replies(*texts):
    it = iter(texts)
    return FakeLLM(lambda messages: next(it))


def test_answer_is_revised_once(prepared) -> None:
    llm = _replies(WRONG, RIGHT)
    result = answer_question(None, QUESTION, embedder=None, reranker=None, llm=llm)
    assert result.answer == RIGHT and not result.warnings
    assert len(llm.calls) == 2
    correction = llm.calls[1][-1].content
    assert "03 người" in correction and "Khoản 2" in correction


def test_failed_revision_keeps_first_answer_with_warning(prepared) -> None:
    llm = _replies(WRONG, WRONG)
    result = answer_question(None, QUESTION, embedder=None, reranker=None, llm=llm)
    assert result.answer == WRONG
    assert any("dẫn nhầm" in w for w in result.warnings)


def test_correct_answer_needs_one_call(prepared) -> None:
    llm = _replies(RIGHT)
    answer_question(None, QUESTION, embedder=None, reranker=None, llm=llm)
    assert len(llm.calls) == 1


def test_stream_resets_and_revises(prepared) -> None:
    events = list(
        stream_answer(None, QUESTION, embedder=None, reranker=None, llm=_replies(WRONG, RIGHT))
    )
    kinds = [k for k, _ in events]
    assert kinds.index("reset") < kinds.index("done")
    after = kinds.index("reset")
    assert "".join(p for k, p in events[after:] if k == "delta") == RIGHT
    assert events[-1][1].answer == RIGHT


def test_matching_clause_of_another_article_does_not_excuse() -> None:
    # Điều khác (ngoại lệ "được chở tối đa 02 người") khớp điều kiện nhưng không thay được Khoản
    # xử phạt bị dẫn nhầm
    exception = hit(
        "36/2024/QH15", "Điều 33", "Khoản 1",
        content="1. Người lái xe mô tô được chở tối đa hai người trong các trường hợp sau:",
    )  # fmt: skip
    q = "Đi xe máy chở theo 2 người bị phạt bao nhiêu?"
    answer = WRONG + " Trường hợp được chở [Điều 33, Khoản 1 - 36/2024/QH15]."
    assert check_answer(q, answer, [*HITS, exception])
