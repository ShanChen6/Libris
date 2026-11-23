import re
from datetime import date

import psycopg
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.generation.answer import REFUSAL_TEXT, answer_question, validity_notices
from app.generation.citations import Citation
from app.generation.llm import LLMError, get_llm
from app.main import app
from app.pipeline.embedding import get_embedder
from app.retrieval.rerank import get_reranker
from tests.fakes import FakeLLM, FakeReranker
from tests.generation.test_citations_prompt import hit
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)

TODAY = date(2026, 11, 23)


def _cite_first(messages) -> str:
    """LLM giả 'ngoan': trích dẫn đúng nhãn của đoạn đầu tiên trong ngữ cảnh."""
    label = re.search(r"Trích dẫn: (\[[^\]]+\])", messages[1].content).group(1)
    return f"Bị phạt tiền từ 400.000 đồng đến 600.000 đồng {label}."


def _ask(seeded, question: str, llm, **kw):  # noqa: F811
    conninfo, emb = seeded
    with psycopg.connect(conninfo) as conn:
        return answer_question(
            conn, question, embedder=emb, reranker=FakeReranker(), llm=llm, today=TODAY,
            candidates=10, top_n=3, **kw,
        )  # fmt: skip


def test_grounded_answer_with_verified_citations(seeded) -> None:  # noqa: F811
    llm = FakeLLM(_cite_first)
    res = _ask(seeded, "xe mô tô không có gương chiếu hậu bên trái bị phạt bao nhiêu", llm)
    assert not res.refused and res.refusal_reason is None
    assert res.citations and all(c.valid for c in res.citations)
    assert res.citations[0].hit.document_number == "168/2024/NĐ-CP"
    assert res.model == "fake-llm" and set(res.timings) == {"retrieval", "llm"}
    system, user = llm.calls[0]
    assert "QUY TẮC BẮT BUỘC" in system.content and "<tai_lieu>" in user.content


def test_low_relevance_refuses_without_calling_llm(seeded) -> None:  # noqa: F811
    llm = FakeLLM("không được gọi")
    res = _ask(seeded, "công thức nấu phở bò", llm, min_rerank_score=0.5)
    assert res.refused and res.refusal_reason == "low_relevance"
    assert res.answer.startswith(REFUSAL_TEXT) and llm.calls == []


def test_model_refusal(seeded) -> None:  # noqa: F811
    res = _ask(seeded, "gương chiếu hậu", FakeLLM("TỪ CHỐI\nTài liệu không nói về vấn đề này."))
    assert res.refused and res.refusal_reason == "model_refused"
    assert res.answer.endswith("Lý do: Tài liệu không nói về vấn đề này.")


def test_ungrounded_answer_is_replaced(seeded) -> None:  # noqa: F811
    # Không trích dẫn, hoặc chỉ trích dẫn Điều không có trong ngữ cảnh -> bị loại
    for reply in ("Bị phạt 10 triệu đồng.", "Bị phạt 10 triệu [Điều 99 - 168/2024/NĐ-CP]."):
        res = _ask(seeded, "gương chiếu hậu", FakeLLM(reply))
        assert res.refused and res.refusal_reason == "ungrounded"
        assert "10 triệu" not in res.answer


def test_partly_invalid_citations_are_reported(seeded) -> None:  # noqa: F811
    res = _ask(
        seeded,
        "gương chiếu hậu",
        FakeLLM(lambda m: _cite_first(m) + " Thêm [Điều 99 - 168/2024/NĐ-CP]."),
    )
    assert not res.refused
    assert res.warnings == ["Trích dẫn [Điều 99 - 168/2024/NĐ-CP] không khớp với đoạn luật nào "
                            "đã cung cấp"]  # fmt: skip


def test_validity_notices() -> None:
    old = hit("100/2019/NĐ-CP", "Điều 6", "Khoản 8", status="AMENDED",
              superseded_by=["repealed:168/2024/NĐ-CP"])  # fmt: skip
    expired = hit("45/2013/QH13", "Điều 129", None, status="EXPIRED",
                  expiry_date=date(2024, 8, 1), replaced_by=["31/2024/QH15"])  # fmt: skip
    cites = [Citation(f"[{i}]", 0, 1, h.document_number, h.article, h.clause, h)
             for i, h in enumerate([old, old, expired, hit()])]  # fmt: skip
    assert validity_notices(cites) == [
        "Điều 6 100/2019/NĐ-CP (hoặc một phần) đã bị bãi bỏ bởi 168/2024/NĐ-CP; quy định này "
        "không còn được áp dụng.",
        "45/2013/QH13 đã hết hiệu lực từ ngày 01/08/2024 và được thay thế bởi 31/2024/QH15.",
    ]


def test_answer_endpoint(seeded) -> None:  # noqa: F811
    conninfo, emb = seeded
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=conninfo, rerank_candidates=10, rerank_top_n=3
    )
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_reranker] = FakeReranker
    try:
        app.dependency_overrides[get_llm] = lambda: FakeLLM(_cite_first)
        client = TestClient(app)
        body = client.post("/answer", json={"question": "gương chiếu hậu bị phạt"}).json()
        assert body["refused"] is False and body["model"] == "fake-llm"
        cite = body["citations"][0]
        assert body["answer"][cite["start"] : cite["end"]] == cite["label"]
        assert {"chunk_id", "char_start", "char_end", "document_title"} <= cite.keys()
        assert body["sources"] and body["plan"]["mode"] == "current"

        class Down(FakeLLM):
            def complete(self, messages):
                raise LLMError("quá tải")

        app.dependency_overrides[get_llm] = lambda: Down("")
        assert client.post("/answer", json={"question": "gương chiếu hậu"}).status_code == 503
        assert client.post("/answer", json={"question": ""}).status_code == 422
    finally:
        app.dependency_overrides.clear()


# --- Streaming (Task 4.2) ---------------------------------------------------------------------
from app.generation.answer import stream_answer  # noqa: E402


def _stream(seeded, question: str, llm, **kw):  # noqa: F811
    conninfo, emb = seeded
    with psycopg.connect(conninfo) as conn:
        return list(
            stream_answer(
                conn, question, embedder=emb, reranker=FakeReranker(), llm=llm, today=TODAY,
                candidates=10, top_n=3, **kw,
            )
        )  # fmt: skip


def test_stream_meta_deltas_done(seeded) -> None:  # noqa: F811
    events = _stream(seeded, "xe mô tô không có gương chiếu hậu bị phạt", FakeLLM(_cite_first))
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and set(kinds[1:-1]) == {"delta"}
    streamed = "".join(d for k, d in events if k == "delta")
    done = events[-1][1]
    assert not done.refused and done.answer.startswith(streamed)
    assert done.model == "fake-llm" and "first_token" in done.timings


def test_stream_never_leaks_refusal_marker(seeded) -> None:  # noqa: F811
    events = _stream(seeded, "gương chiếu hậu", FakeLLM("TỪ CHỐI\nTài liệu không đủ căn cứ."))
    assert [k for k, _ in events] == ["meta", "done"]
    assert events[-1][1].refusal_reason == "model_refused"


def test_stream_ungrounded_answer_is_replaced_in_done(seeded) -> None:  # noqa: F811
    events = _stream(seeded, "gương chiếu hậu", FakeLLM("Bị phạt 10 triệu đồng."))
    assert "".join(d for k, d in events if k == "delta") == "Bị phạt 10 triệu đồng."
    done = events[-1][1]
    assert done.refused and done.refusal_reason == "ungrounded" and "10 triệu" not in done.answer


def test_stream_short_answer_and_early_refusal(seeded) -> None:  # noqa: F811
    short = _stream(seeded, "gương chiếu hậu", FakeLLM("Có."))
    assert [d for k, d in short if k == "delta"] == ["Có."]
    llm = FakeLLM("không được gọi")
    early = _stream(seeded, "nấu phở bò", llm, min_rerank_score=0.5)
    assert [k for k, _ in early] == ["meta", "done"] and llm.calls == []
    assert early[-1][1].refusal_reason == "low_relevance"


def test_stream_llm_error_event(seeded) -> None:  # noqa: F811
    class Broken(FakeLLM):
        def stream(self, messages):
            yield "Bị phạt"
            raise LLMError("đứt kết nối")

    events = _stream(seeded, "gương chiếu hậu", Broken(""))
    assert events[-1][0] == "error" and "đứt kết nối" in events[-1][1]["message"]


def test_stream_endpoint(seeded) -> None:  # noqa: F811
    import json

    conninfo, emb = seeded
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=conninfo, rerank_candidates=10, rerank_top_n=3
    )
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_reranker] = FakeReranker
    app.dependency_overrides[get_llm] = lambda: FakeLLM(_cite_first)
    try:
        with TestClient(app).stream(
            "POST", "/answer/stream", json={"question": "gương chiếu hậu bị phạt"}
        ) as res:
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            body = "".join(res.iter_text())
    finally:
        app.dependency_overrides.clear()
    events = [
        (block.split("\n")[0].removeprefix("event: "), json.loads(block.split("\n")[1][6:]))
        for block in body.strip().split("\n\n")
    ]
    assert events[0][0] == "meta" and events[0][1]["sources"]
    assert events[0][1]["plan"]["mode"] == "current"
    assert {k for k, _ in events[1:-1]} == {"delta"}
    done = events[-1][1]
    assert events[-1][0] == "done" and done["refused"] is False and done["citations"]
    assert done["answer"].startswith("".join(d["text"] for k, d in events if k == "delta"))


def test_truncated_answer_is_flagged(seeded) -> None:  # noqa: F811
    class Cut(FakeLLM):
        last_finish_reason = "content_filter"

    res = _ask(seeded, "gương chiếu hậu", Cut(lambda m: _cite_first(m) + "\n  *"))
    assert not res.refused and not res.answer.rstrip().endswith("*")
    assert any("chưa đầy đủ" in w and "content_filter" in w for w in res.warnings)
    events = _stream(seeded, "gương chiếu hậu", Cut(lambda m: _cite_first(m) + "\n2."))
    assert any("chưa đầy đủ" in w for w in events[-1][1].warnings)
    assert not events[-1][1].answer.endswith("2.")
