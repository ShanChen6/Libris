import json
import re
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.analysis.contract import AnalysisError, analyze_contract, locate_quote, parse_json
from app.core.config import Settings, get_settings
from app.generation.llm import get_llm
from app.main import app
from app.pipeline.embedding import get_embedder
from app.retrieval.rerank import get_reranker
from tests.fakes import FakeLLM, FakeReranker
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)

CONTRACT = (
    "HỢP ĐỒNG THUÊ XE\n"
    "Điều 1. Bên A cho Bên B thuê một xe mô tô biển số 29A-123.45 trong thời hạn 12 tháng.\n"
    "Điều 2. Giá thuê là 1.500.000 đồng mỗi tháng, thanh toán vào ngày 05 hằng tháng.\n"
    "Điều 3. Bên B   chịu toàn bộ   tiền phạt khi xe không có gương chiếu hậu bên trái, kể cả "
    "khi xe được giao như vậy.\n"
    "Điều 4. Bên A được đơn phương chấm dứt hợp đồng bất cứ lúc nào mà không phải bồi thường.\n"
)
READ = {
    "document_type": "Hợp đồng thuê tài sản",
    "parties": [{"role": "Bên cho thuê (Bên A)", "name": "Nguyễn Văn A"}],
    "summary": "Bên A cho Bên B thuê xe mô tô 12 tháng, giá 1.500.000 đồng/tháng.",
    "key_terms": [
        {"topic": "Giá thuê", "content": "1.500.000 đồng/tháng",
         "quote": "Giá thuê là 1.500.000 đồng mỗi tháng"},
        {"topic": "", "content": "bị bỏ vì thiếu chủ đề"},
    ],
    "issues": [
        {"title": "Bên B chịu phạt thay", "affected_party": "Bên B",
         "quote": "Bên B chịu toàn bộ tiền phạt khi xe không có gương chiếu hậu bên trái",
         "concern": "Lỗi thiết bị của xe do Bên A giao nhưng Bên B chịu phạt",
         "legal_query": "xe mô tô không có gương chiếu hậu bên trái bị phạt bao nhiêu"},
        {"title": "Bên A đơn phương chấm dứt", "affected_party": "Bên B",
         "quote": "Bên A được quyền chấm dứt hợp đồng khi muốn",  # LLM chép sai nguyên văn
         "concern": "Không báo trước, không bồi thường",
         "legal_query": "công thức nấu phở bò"},  # không có luật liên quan trong kho thử
    ],
}  # fmt: skip


def _fake(messages) -> str:
    user = messages[1].content
    if "<van_ban>" in user:
        return "```json\n" + json.dumps(READ, ensure_ascii=False) + "\n```"
    assert "<van_de>" in user and "Đoạn luật liên quan: không có" in user
    label = re.search(r"Trích dẫn: (\[[^\]]+\])", user).group(1)
    return json.dumps(
        {"assessments": [
            {"id": 1, "severity": "medium",
             "verdict": f"Xe không có gương bị phạt tiền {label}. Sai [Điều 99 - 168/2024/NĐ-CP].",
             "recommendation": "Ghi rõ Bên A chịu trách nhiệm về tình trạng xe khi giao."},
            {"id": 2, "severity": "high", "verdict": "Điều khoản trái luật.",
             "recommendation": "Bổ sung thời hạn báo trước."},
        ]},
        ensure_ascii=False,
    )  # fmt: skip


def test_parse_json() -> None:
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Kết quả: {"a": [1, 2]} xong') == {"a": [1, 2]}
    for bad in ("không có json", "{a: 1}", "[1, 2]"):
        with pytest.raises(AnalysisError):
            parse_json(bad)


def test_locate_quote() -> None:
    q = locate_quote(CONTRACT, "bên b chịu toàn bộ tiền phạt")  # khác khoảng trắng, hoa/thường
    assert q and q.verified and CONTRACT[q.start : q.end] == "Bên B   chịu toàn bộ   tiền phạt"
    q = locate_quote(CONTRACT, "“Giá thuê là 1.500.000 đồng ... thanh toán vào ngày 05”")
    assert q and q.verified and CONTRACT[q.start : q.end] == "Giá thuê là 1.500.000 đồng"
    missing = locate_quote(CONTRACT, "Bên B được miễn mọi trách nhiệm")
    assert missing and not missing.verified
    assert locate_quote(CONTRACT, None) is None and locate_quote(CONTRACT, "  ") is None


def _run(seeded, text: str, llm):  # noqa: F811
    conninfo, emb = seeded
    with psycopg.connect(conninfo) as conn:
        events = list(analyze_contract(
            conn, text, embedder=emb, reranker=FakeReranker(), llm=llm,
            candidates=10, passages_per_issue=2, today=date(2026, 11, 23),
        ))  # fmt: skip
    return events


def test_analysis_grounds_issues_in_law(seeded) -> None:  # noqa: F811
    llm = FakeLLM(_fake)
    events = _run(seeded, CONTRACT, llm)
    steps = [e[1]["step"] for e in events if e[0] == "progress"]
    assert steps == ["read", "retrieve", "retrieve", "assess"]
    assert llm.json_modes == [True, True]
    kind, res = events[-1]
    assert kind == "done" and res.document_type == "Hợp đồng thuê tài sản"
    assert [t.topic for t in res.key_terms] == ["Giá thuê"] and res.key_terms[0].quote.verified

    grounded, ungrounded = sorted(res.issues, key=lambda i: i.id)
    # Có căn cứ: thẻ hợp lệ được giữ, thẻ bịa bị báo
    assert grounded.severity == "medium" and grounded.grounded
    assert grounded.quote.verified
    assert grounded.citations[0].hit.document_number == "168/2024/NĐ-CP"
    assert grounded.citations[0].hit.document_id
    assert "Trích dẫn không khớp đoạn luật nào: [Điều 99 - 168/2024/NĐ-CP]" in grounded.warnings
    # Không có đoạn luật nào: kết luận nặng mà không có căn cứ bị gắn cờ; trích dẫn sai nguyên văn
    assert ungrounded.hits == [] and not ungrounded.grounded and not ungrounded.quote.verified
    assert any("chưa có căn cứ pháp lý" in w for w in ungrounded.warnings)
    assert any("Không tìm thấy nguyên văn" in w for w in ungrounded.warnings)
    assert [i.id for i in res.issues] == [2, 1]  # high trước medium
    assert res.text == CONTRACT.strip() and not res.truncated


def test_long_text_is_truncated_and_short_text_rejected(seeded) -> None:  # noqa: F811
    llm = FakeLLM(_fake)
    conninfo, emb = seeded
    with psycopg.connect(conninfo) as conn:
        events = list(analyze_contract(
            conn, CONTRACT * 3, embedder=emb, reranker=FakeReranker(), llm=llm, max_chars=500,
            candidates=10,
        ))  # fmt: skip
        assert events[-1][1].truncated and "chỉ 500 ký tự đầu" in events[-1][1].warnings[0]
        assert len(llm.calls[0][1].content) < 600
        with pytest.raises(AnalysisError):
            list(analyze_contract(conn, "quá ngắn", embedder=emb, reranker=None, llm=llm))


def test_invalid_json_is_retried_then_reported(seeded) -> None:  # noqa: F811
    replies = iter(["không phải json", json.dumps({"document_type": "Khác", "issues": []})])
    res = _run(seeded, CONTRACT, FakeLLM(lambda m: next(replies)))[-1][1]
    assert res.document_type == "Khác" and res.issues == []
    with pytest.raises(AnalysisError, match="không đúng định dạng"):
        _run(seeded, CONTRACT, FakeLLM("vẫn không phải json"))


def test_assessment_failure_keeps_summary_and_related_law(seeded) -> None:  # noqa: F811
    from app.generation.llm import LLMError

    def reply(messages):
        if "<van_ban>" in messages[1].content:
            return json.dumps(READ, ensure_ascii=False)
        raise LLMError("503 quá tải")

    res = _run(seeded, CONTRACT, FakeLLM(reply))[-1][1]
    assert res.summary and len(res.issues) == 2
    assert all(i.severity == "unclear" and not i.citations for i in res.issues)
    assert any("Chưa đối chiếu được" in w for w in res.warnings)
    assert next(i for i in res.issues if i.id == 1).hits  # quy định liên quan vẫn còn


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_api_stream(seeded) -> None:  # noqa: F811
    conninfo, emb = seeded
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=conninfo, rerank_candidates=10
    )
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_reranker] = FakeReranker
    app.dependency_overrides[get_llm] = lambda: FakeLLM(_fake)
    try:
        client = TestClient(app)
        res = client.post("/analyze/stream", data={"text": CONTRACT})
        assert res.status_code == 200 and res.headers["content-type"].startswith(
            "text/event-stream"
        )
        events = _events(res.text)
        assert events[0] == (
            "progress",
            {"step": "read", "message": "Đang đọc và tóm tắt văn bản…"},
        )
        kind, done = events[-1]
        assert kind == "done" and done["disclaimer"]
        cite = next(i for i in done["issues"] if i["id"] == 1)["citations"][0]
        assert cite["document_id"] and cite["label"].startswith("[Điều")
        assert cite["char_end"] > cite["char_start"]
        related = next(i for i in done["issues"] if i["id"] == 1)["related"]
        assert related and related[0]["label"].startswith("[Điều") and related[0]["document_id"]

        assert client.post("/analyze/stream").status_code == 422  # thiếu dữ liệu
        bad = client.post("/analyze/stream", files={"file": ("a.txt", b"x", "text/plain")})
        assert bad.status_code == 422 and ".pdf" in bad.json()["detail"]
        both = client.post(
            "/analyze/stream", data={"text": CONTRACT}, files={"file": ("a.pdf", b"%PDF", "x")}
        )
        assert both.status_code == 422
        short = _events(client.post("/analyze/stream", data={"text": "ngắn"}).text)
        assert short[-1][0] == "error" and "Không đọc được đủ nội dung" in short[-1][1]["message"]
    finally:
        app.dependency_overrides.clear()
