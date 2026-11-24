import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.generation.followup import contextualize, is_follow_up
from app.generation.llm import get_llm
from app.main import app
from app.pipeline.embedding import get_embedder
from app.retrieval.rerank import get_reranker
from tests.fakes import FakeLLM, FakeReranker
from tests.generation.test_answer import _cite_first
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)


@pytest.mark.parametrize(
    "q",
    ["Còn ô tô thì sao?", "Thế còn xe đạp?", "Nếu tái phạm thì sao?", "Trường hợp đó bị phạt gì?",
     "Mức này áp dụng từ khi nào?", "ô tô thì sao"],
)  # fmt: skip
def test_follow_up_questions(q: str) -> None:
    assert is_follow_up(q)


@pytest.mark.parametrize(
    "q",
    ["Xe máy vượt đèn đỏ bị phạt bao nhiêu tiền?", "Tuổi kết hôn của nam và nữ là bao nhiêu?",
     "Thời gian thử việc tối đa đối với công việc cần trình độ cao đẳng là bao lâu?"],
)  # fmt: skip
def test_standalone_questions(q: str) -> None:
    assert not is_follow_up(q)


def test_contextualize() -> None:
    history = ["Nam bao nhiêu tuổi thì được kết hôn?", "Xe máy vượt đèn đỏ bị phạt bao nhiêu?"]
    assert contextualize("Còn ô tô thì sao?", history) == (
        "Xe máy vượt đèn đỏ bị phạt bao nhiêu? Hỏi tiếp: Còn ô tô thì sao?"
    )
    assert contextualize("Còn ô tô thì sao?", []) == "Còn ô tô thì sao?"
    q = "Tuổi kết hôn của nam và nữ là bao nhiêu?"
    assert contextualize(q, history) == q


def test_api_uses_history_for_follow_up(seeded) -> None:  # noqa: F811
    conninfo, emb = seeded
    llm = FakeLLM(_cite_first)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=conninfo, rerank_candidates=10, rerank_top_n=3
    )
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_reranker] = FakeReranker
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        body = TestClient(app).post("/answer", json={
            "question": "còn vượt đèn đỏ thì sao?",
            "history": ["xe mô tô không có gương chiếu hậu bên trái bị phạt bao nhiêu"],
        }).json()  # fmt: skip
        assert body["refused"] is False
        assert "gương chiếu hậu" in body["question"] and "Hỏi tiếp" in body["question"]
        assert "Hỏi tiếp: còn vượt đèn đỏ thì sao?" in llm.calls[0][1].content
    finally:
        app.dependency_overrides.clear()
