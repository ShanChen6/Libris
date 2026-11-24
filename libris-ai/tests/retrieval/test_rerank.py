from datetime import date

import numpy as np
import psycopg

from app.retrieval.hybrid import FusedHit
from app.retrieval.rerank import CrossEncoderReranker, rerank
from app.retrieval.service import make_plan, retrieve
from tests.fakes import FakeReranker
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)


def _hit(i: int, content: str) -> FusedHit:
    return FusedHit(
        chunk_id=str(i), document_number="1/2024/QH15", document_title="", status="ACTIVE",
        effective_date=None, expiry_date=None, article=f"Điều {i}", clause=None, point=None,
        context_prefix="[Văn bản]", content=content, char_start=0, char_end=1, score=1 / (60 + i),
        vec_rank=i, kw_rank=None, ref_rank=None,
    )  # fmt: skip


def test_rerank_reorders_and_keeps_hybrid_rank() -> None:
    hits = [_hit(1, "đăng ký kết hôn"), _hit(2, "tuổi kết hôn nam 20 nữ 18"), _hit(3, "ly hôn")]
    out = rerank("tuổi kết hôn nam nữ", hits, FakeReranker(), top_n=2)
    assert [h.article for h in out] == ["Điều 2", "Điều 1"]
    assert [h.hybrid_rank for h in out] == [2, 1]
    assert out[0].rerank_score is not None and out[0].rerank_score > out[1].rerank_score
    assert hits[1].rerank_score is None  # không sửa danh sách gốc
    assert rerank("x", [], FakeReranker()) == []


def test_rerank_ties_keep_hybrid_order() -> None:
    hits = [_hit(1, "a"), _hit(2, "b"), _hit(3, "c")]
    assert [h.article for h in rerank("zzz", hits, FakeReranker(), top_n=3)] == [
        "Điều 1", "Điều 2", "Điều 3",
    ]  # fmt: skip


def test_cross_encoder_converts_logits_to_probabilities() -> None:
    class _Model:
        def predict(self, pairs, **_kw):
            return np.array([2.0, -2.0, 0.0])

    rr = CrossEncoderReranker("x")
    rr._model = _Model()  # type: ignore[assignment]
    scores = rr.score("q", ["a", "b", "c"])
    assert np.all((scores > 0) & (scores < 1)) and scores[0] > scores[2] > scores[1]
    assert rr.score("q", []).shape == (0,)


def test_make_plan_overrides() -> None:
    plan = make_plan("gương chiếu hậu", include_expired=True)
    assert plan.mode == "compare" and "EXPIRED" in plan.statuses
    plan = make_plan("gương chiếu hậu", as_of=date(2022, 1, 1))
    assert plan.mode == "point_in_time" and plan.period == (date(2022, 1, 1), date(2022, 1, 1))
    assert "EXPIRED" not in make_plan("so sánh luật cũ", include_expired=False).statuses


def test_retrieve_pipeline(seeded) -> None:  # noqa: F811
    conninfo, emb = seeded
    rr = FakeReranker()
    with psycopg.connect(conninfo) as conn:
        res = retrieve(conn, "xe máy không có gương chiếu hậu", emb, rr, candidates=6, top_n=2)
        assert res.reranked and len(res.hits) <= 2
        assert res.expanded_query.startswith("xe máy không có gương chiếu hậu (")
        assert rr.calls[0][0] == res.expanded_query  # rerank bằng câu đã mở rộng
        assert all(h.rerank_score is not None for h in res.hits)
        assert res.hits[0].document_number == "168/2024/NĐ-CP"

        no_rr = retrieve(conn, "gương chiếu hậu", emb, None, top_n=3)
        assert not no_rr.reranked and all(h.rerank_score is None for h in no_rr.hits)


def test_balance_old_and_new() -> None:
    from app.retrieval.service import balance_old_and_new

    old = [_hit(i, "cũ") for i in range(1, 6)]
    for h in old:
        h.superseded_by = ["repealed:X"]
    new = [_hit(i, "mới") for i in range(6, 8)]
    picked = balance_old_and_new(old + new, 5)  # 5 đoạn cũ xếp trên, 2 đoạn mới xếp dưới
    assert len(picked) == 5
    assert sum(1 for h in picked if not h.superseded_by) == 2
    assert [h.article for h in picked] == ["Điều 1", "Điều 2", "Điều 3", "Điều 6", "Điều 7"]
    assert balance_old_and_new(old, 3) == old[:3]  # không có đoạn mới -> theo thứ hạng


def test_reranker_can_be_disabled(monkeypatch) -> None:
    from app.core.config import Settings
    from app.retrieval import rerank as module

    monkeypatch.setattr(module, "get_settings", lambda: Settings(reranker_enabled=False))
    module.get_reranker.cache_clear()
    try:
        assert module.get_reranker() is None  # không tải mô hình
    finally:
        module.get_reranker.cache_clear()


def test_specialized_domains_are_demoted_unless_asked() -> None:
    from dataclasses import replace

    from app.retrieval.service import disambiguate

    moto = replace(_hit(7, "x"), context_prefix="[Điều 7: Xử phạt người điều khiển xe mô tô]")
    special = replace(
        _hit(8, "x"), context_prefix="[Điều 8: Xử phạt người điều khiển xe máy chuyên dùng]"
    )
    moto, special = replace(moto, rerank_score=0.6), replace(special, rerank_score=0.8)
    assert [h.article for h in disambiguate("xe máy chạy quá tốc độ", [moto, special])] == [
        "Điều 7",
        "Điều 8",
    ]
    asked = disambiguate("xe máy chuyên dùng chạy quá tốc độ", [moto, special])
    assert [h.article for h in asked] == ["Điều 8", "Điều 7"]
