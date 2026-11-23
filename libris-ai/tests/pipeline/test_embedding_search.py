import psycopg

from app.pipeline.embedding import chunk_text
from app.pipeline.search import Hit, keyword_search, semantic_search
from app.pipeline.store import chunk_documents, embed_chunks
from tests.fakes import FakeEmbedder

DOCS = {
    "168/2024/NĐ-CP": (
        "ACTIVE",
        "Điều 1. Xử phạt người điều khiển xe mô tô\n"
        "1. Phạt tiền từ 400.000 đồng đến 600.000 đồng đối với hành vi không có gương chiếu hậu "
        "bên trái.\n"
        "2. Phạt tiền từ 800.000 đồng đến 1.000.000 đồng đối với hành vi vượt đèn đỏ.",
    ),
    "100/2019/NĐ-CP": (
        "EXPIRED",
        "Điều 1. Xử phạt người điều khiển xe mô tô\n"
        "1. Phạt tiền từ 100.000 đồng đến 200.000 đồng đối với hành vi không có gương chiếu hậu "
        "bên trái.",
    ),
    "52/2014/QH13": (
        "ACTIVE",
        "Điều 1. Độ tuổi kết hôn\nNam từ đủ 20 tuổi trở lên, nữ từ đủ 18 tuổi trở lên.",
    ),
}


def _seed(conninfo: str) -> None:
    with psycopg.connect(conninfo) as conn:
        for i, (number, (status, text)) in enumerate(DOCS.items()):
            conn.execute(
                "INSERT INTO legal_documents (document_number, document_type, title, status, "
                "full_text, source, source_id) "
                "VALUES (%s, 'Nghị định', 'Văn bản', %s, %s, 't', %s)",
                (number, status, text, str(i)),
            )
    chunk_documents(conninfo, max_chars=120)


def test_chunk_text() -> None:
    assert chunk_text("[Văn bản: X | Điều 1]", "Nội dung") == "[Văn bản: X | Điều 1]\nNội dung"


def test_embed_is_incremental_and_resumable(pg_conninfo: str) -> None:
    _seed(pg_conninfo)
    emb = FakeEmbedder()
    first = embed_chunks(pg_conninfo, emb, batch_size=2)
    with psycopg.connect(pg_conninfo) as conn:
        total, with_vec, with_tokens = conn.execute(
            "SELECT count(*), count(embedding), count(token_count) FROM legal_chunks"
        ).fetchone()  # type: ignore[misc]
    assert first.embedded == total == with_vec == with_tokens
    assert emb.calls == -(-total // 2)  # mỗi lô một lần gọi mô hình

    assert embed_chunks(pg_conninfo, emb).embedded == 0  # không làm lại đoạn đã có
    assert embed_chunks(pg_conninfo, emb, force=True).embedded == total
    assert embed_chunks(pg_conninfo, emb, force=True, document_numbers=["52/2014/QH13"]).embedded
    assert first.over_limit == 0


def test_search_respects_status_filter(pg_conninfo: str) -> None:
    _seed(pg_conninfo)
    emb = FakeEmbedder()
    embed_chunks(pg_conninfo, emb)
    query = "không có gương chiếu hậu bên trái bị phạt bao nhiêu"
    q = emb.encode([query])[0]
    with psycopg.connect(pg_conninfo) as conn:
        hits = semantic_search(conn, q, k=3)
        assert hits[0].document_number == "168/2024/NĐ-CP"
        assert "gương chiếu hậu" in hits[0].content
        assert all(h.status in ("ACTIVE", "AMENDED") for h in hits)
        assert hits[0].score >= hits[-1].score

        with_expired = semantic_search(conn, q, k=10, statuses=("ACTIVE", "EXPIRED"))
        assert "100/2019/NĐ-CP" in {h.document_number for h in with_expired}

        kw = keyword_search(conn, "gương chiếu hậu", k=5)
        assert kw and {h.document_number for h in kw} == {"168/2024/NĐ-CP"}
        # Số hiệu văn bản có trong tiền tố ngữ cảnh -> tìm được theo số hiệu
        by_number = keyword_search(conn, "100/2019/NĐ-CP ???", k=5, statuses=("EXPIRED",))
        assert by_number and {h.document_number for h in by_number} == {"100/2019/NĐ-CP"}
        assert keyword_search(conn, "100/2019/NĐ-CP", k=5) == []  # mặc định bỏ văn bản hết hiệu lực
        assert keyword_search(conn, "   ", k=5) == []

        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'legal_chunks' "
                "AND schemaname = current_schema()"
            ).fetchall()
        }
    assert {"legal_chunks_embedding_hnsw_idx", "legal_chunks_search_vector_idx"} <= indexes


def test_hit_citation() -> None:
    hit = Hit("1", "168/2024/NĐ-CP", "ACTIVE", "Điều 7", "Khoản 2", "Điểm a", "", "", 0.9)
    assert hit.citation == "[Điều 7, Khoản 2, Điểm a - 168/2024/NĐ-CP]"
    assert Hit("1", "X", "ACTIVE", None, None, None, "", "", 0).citation == "[Văn bản - X]"
