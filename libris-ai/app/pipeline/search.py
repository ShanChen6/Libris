"""Truy vấn tìm kiếm trên legal_chunks: ngữ nghĩa (vector) và từ khóa (full-text).

Đây là hai luồng nền tảng; Task 3.1 sẽ hợp nhất chúng bằng Reciprocal Rank Fusion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

# Mặc định chỉ trả lời theo văn bản còn hiệu lực (Task 3.2 sẽ thêm Query Router).
IN_FORCE = ("ACTIVE", "AMENDED")

_SELECT = """
SELECT c.id, d.document_number, d.status::text, c.article, c.clause, c.point,
       c.context_prefix, c.content, {score} AS score
FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id
WHERE d.status::text = ANY(%(statuses)s) AND {cond}
ORDER BY {order}
LIMIT %(k)s
"""


@dataclass
class Hit:
    chunk_id: str
    document_number: str
    status: str
    article: str | None
    clause: str | None
    point: str | None
    context_prefix: str
    content: str
    score: float

    @property
    def citation(self) -> str:
        parts = [p for p in (self.article, self.clause, self.point) if p]
        return f"[{', '.join(parts) or 'Văn bản'} - {self.document_number}]"


def _hits(rows: list[tuple]) -> list[Hit]:
    return [Hit(str(r[0]), *r[1:8], float(r[8])) for r in rows]


def semantic_search(
    conn: psycopg.Connection,
    query_vector: np.ndarray,
    *,
    k: int = 20,
    statuses: tuple[str, ...] = IN_FORCE,
    ef_search: int = 100,
) -> list[Hit]:
    """Top-k đoạn gần nhất theo cosine (dùng chỉ mục HNSW)."""
    register_vector(conn)
    # Lọc theo trạng thái sau khi quét HNSW: tăng ef_search và bật iterative scan (pgvector ≥ 0.8)
    # để vẫn đủ k kết quả khi nhiều đoạn gần nhất thuộc văn bản hết hiệu lực.
    conn.execute(f"SET hnsw.ef_search = {int(ef_search)}")
    conn.execute("SET hnsw.iterative_scan = relaxed_order")
    sql = _SELECT.format(
        score="1 - (c.embedding <=> %(q)s)",
        cond="c.embedding IS NOT NULL",
        order="c.embedding <=> %(q)s",
    )
    rows = conn.execute(sql, {"q": query_vector, "k": k, "statuses": list(statuses)}).fetchall()
    return _hits(rows)


def keyword_search(
    conn: psycopg.Connection,
    query: str,
    *,
    k: int = 20,
    statuses: tuple[str, ...] = IN_FORCE,
) -> list[Hit]:
    """Top-k đoạn khớp từ khóa (OR các từ), xếp hạng ts_rank_cd (dùng chỉ mục GIN)."""
    sql = _SELECT.format(
        score="ts_rank_cd(c.search_vector, q)",
        cond="c.search_vector @@ q",
        order="score DESC",
    ).replace(
        "ON d.id = c.document_id",
        "ON d.id = c.document_id CROSS JOIN to_tsquery('simple', %(tsq)s) q",
    )
    words = [w for w in "".join(ch if ch.isalnum() or ch in "/-" else " " for ch in query).split()]
    if not words:
        return []
    tsq = " | ".join(f"'{w.lower()}'" for w in words)
    rows = conn.execute(sql, {"tsq": tsq, "k": k, "statuses": list(statuses)}).fetchall()
    return _hits(rows)
