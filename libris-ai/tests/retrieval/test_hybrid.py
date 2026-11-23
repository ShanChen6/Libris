from datetime import date

import psycopg
import pytest

from app.pipeline.store import chunk_documents, embed_chunks
from app.retrieval.hybrid import SearchWeights, hybrid_search, tsquery_terms
from app.retrieval.router import route
from tests.fakes import FakeEmbedder

# (số hiệu, tiêu đề, trạng thái, hiệu lực, hết hiệu lực, năm ban hành, nội dung)
DOCS = [
    ("168/2024/NĐ-CP", "Quy định xử phạt giao thông đường bộ", "ACTIVE", "2025-01-01", None,
     "2024-12-26",
     "Điều 7. Xử phạt người điều khiển xe mô tô\n"
     "1. Phạt tiền từ 400.000 đồng đến 600.000 đồng đối với người điều khiển xe mô tô không có "
     "gương chiếu hậu bên trái.\n"
     "2. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng đối với hành vi vượt đèn đỏ."),
    ("100/2019/NĐ-CP", "Quy định xử phạt giao thông đường bộ và đường sắt", "EXPIRED",
     "2020-01-01", "2025-01-01", "2019-12-30",
     "Điều 6. Xử phạt người điều khiển xe mô tô\n"
     "1. Phạt tiền từ 100.000 đồng đến 200.000 đồng đối với người điều khiển xe mô tô không có "
     "gương chiếu hậu bên trái.\n"
     "2. Phạt tiền từ 800.000 đồng đến 1.000.000 đồng đối với hành vi vượt đèn đỏ."),
    ("45/2013/QH13", "Luật Đất đai", "EXPIRED", "2014-07-01", "2024-08-01", "2013-11-29",
     "Điều 1. Hạn mức giao đất nông nghiệp\nHạn mức giao đất trồng cây hàng năm không quá 03 "
     "héc ta."),
    ("31/2024/QH15", "Luật Đất đai", "AMENDED", "2024-08-01", None, "2024-01-18",
     "Điều 1. Hạn mức giao đất nông nghiệp\nHạn mức giao đất trồng cây hằng năm không quá 03 "
     "héc ta cho mỗi loại đất."),
]  # fmt: skip


@pytest.fixture
def seeded(pg_conninfo: str) -> tuple[str, FakeEmbedder]:
    with psycopg.connect(pg_conninfo) as conn:
        for i, (num, title, status, eff, exp, issue, text) in enumerate(DOCS):
            conn.execute(
                "INSERT INTO legal_documents (document_number, document_type, title, status, "
                "effective_date, expiry_date, issue_date, full_text, source, source_id) "
                "VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, 't', %s)",
                (num, title, status, eff, exp, issue, text, str(i)),
            )
        conn.execute(
            "INSERT INTO document_relations VALUES ('168/2024/NĐ-CP', '100/2019/NĐ-CP', "
            "'replaces', '2025-01-01', 'Nghị định 100/2019/NĐ-CP hết hiệu lực')"
        )
    chunk_documents(pg_conninfo, max_chars=160)
    emb = FakeEmbedder()
    embed_chunks(pg_conninfo, emb)
    return pg_conninfo, emb


def _search(seeded: tuple[str, FakeEmbedder], query: str, **kw):
    conninfo, emb = seeded
    with psycopg.connect(conninfo) as conn:
        return hybrid_search(conn, query, emb.encode([query])[0], **kw)


def test_tsquery_terms() -> None:
    assert tsquery_terms("Xe máy không có gương chiếu hậu bị phạt không?") == (
        "'xe' | 'máy' | 'gương' | 'chiếu' | 'hậu' | 'phạt'"
    )
    assert tsquery_terms("Nghị định 168/2024/NĐ-CP") == "'nghị' | 'định' | '168/2024/nđ-cp'"
    assert tsquery_terms("có không là gì?") == ""


def test_default_returns_only_documents_in_force(seeded) -> None:
    res = _search(seeded, "xe mô tô không có gương chiếu hậu bên trái bị phạt bao nhiêu")
    assert res.plan.mode == "current"
    assert res.hits[0].document_number == "168/2024/NĐ-CP"
    assert "400.000" in res.hits[0].content
    assert {h.document_number for h in res.hits} <= {"168/2024/NĐ-CP", "31/2024/QH15"}
    top = res.hits[0]
    assert top.vec_rank == 1 and top.kw_rank == 1  # cả hai luồng cùng xếp đầu
    assert top.score == pytest.approx(2 / 61)
    assert [h.score for h in res.hits] == sorted((h.score for h in res.hits), reverse=True)


def test_compare_query_includes_expired_with_replacement_info(seeded) -> None:
    res = _search(seeded, "So sánh mức phạt không có gương chiếu hậu cũ và mới")
    numbers = {h.document_number for h in res.hits}
    assert {"168/2024/NĐ-CP", "100/2019/NĐ-CP"} <= numbers
    old = next(h for h in res.hits if h.document_number == "100/2019/NĐ-CP")
    assert old.status == "EXPIRED" and old.replaced_by == ["168/2024/NĐ-CP"]


def test_referenced_expired_document_is_searched_and_boosted(seeded) -> None:
    res = _search(seeded, "Nghị định 100/2019/NĐ-CP phạt vượt đèn đỏ bao nhiêu")
    assert res.plan.referenced == ["100/2019/NĐ-CP"]
    assert res.hits[0].document_number == "100/2019/NĐ-CP"
    assert res.hits[0].ref_rank is not None


def test_named_document_is_resolved(seeded) -> None:
    res = _search(seeded, "Theo Luật Đất đai 2013 hạn mức giao đất nông nghiệp")
    assert res.plan.referenced == ["45/2013/QH13"]
    assert res.hits[0].document_number == "45/2013/QH13"


def test_point_in_time_uses_validity_period(seeded) -> None:
    res = _search(seeded, "Vào năm 2022 không có gương chiếu hậu bị phạt bao nhiêu")
    assert res.plan.period == (date(2022, 1, 1), date(2022, 12, 31))
    numbers = {h.document_number for h in res.hits}
    assert "100/2019/NĐ-CP" in numbers  # còn hiệu lực năm 2022
    assert "168/2024/NĐ-CP" not in numbers  # chưa có hiệu lực năm 2022

    land = _search(seeded, "tại thời điểm ngày 15/6/2024 hạn mức giao đất nông nghiệp")
    land_numbers = {h.document_number for h in land.hits}
    assert land.hits[0].document_number == "45/2013/QH13"  # còn hiệu lực đến 01/8/2024
    assert "31/2024/QH15" not in land_numbers  # có hiệu lực từ 01/8/2024


def test_weights_and_top_k(seeded) -> None:
    only_kw = _search(
        seeded, "gương chiếu hậu", top_k=1, weights=SearchWeights(vector=0.0, keyword=1.0)
    )
    assert len(only_kw.hits) == 1 and only_kw.hits[0].kw_rank == 1
    plan = route("gương chiếu hậu")
    plan.statuses = ("EXPIRED",)
    expired_only = _search(seeded, "gương chiếu hậu", plan=plan)
    assert {h.document_number for h in expired_only.hits} <= {"100/2019/NĐ-CP", "45/2013/QH13"}
    assert expired_only.hits[0].citation.endswith("- 100/2019/NĐ-CP]")
