"""Task 3.1 – Hybrid Search: vector + full-text trên PostgreSQL, hợp nhất bằng RRF.

Reciprocal Rank Fusion:

    RRF(d) = Σ_i  w_i / (k + rank_i(d))        (k = 60, rank bắt đầu từ 1)

Ba danh sách xếp hạng được tính trong cùng một câu SQL:

- ``vec``: top-N theo khoảng cách cosine của embedding (chỉ mục HNSW) – bắt ý định câu hỏi đời
  thường ("đi xe máy không gương có bị phạt không").
- ``kw``: top-N theo ``ts_rank_cd`` của full-text (chỉ mục GIN) – bắt chính xác số hiệu văn bản,
  thuật ngữ pháp lý.
- ``ref`` (khi câu hỏi nêu đích danh văn bản): top-N theo vector nhưng chỉ trong các văn bản đó.

Phạm vi văn bản do Query Router (Task 3.2) quyết định: theo trạng thái hiệu lực hiện tại, hoặc theo
khoảng thời gian có hiệu lực.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.pipeline.vn import fz
from app.retrieval.router import RetrievalPlan, normalize_number, route

RRF_K = 60

# Hư từ tiếng Việt: xuất hiện ở hầu hết đoạn luật/câu hỏi nên chỉ làm nhiễu xếp hạng từ khóa.
STOPWORDS = frozenset(
    """
    à ạ ai anh bao bị bởi các cái cần cho chị chỉ có của cũng đã đang đâu để đến đó em gì hay
    hãy hỏi hoặc khi không là làm lại mà mình nào này nên nếu như những nhiêu ơi phải ra rằng
    rồi sao sẽ tại thế thì tôi trên trong từ và vậy vào với xin được bạn vừa
    """.split()
)

_WORD_RE = re.compile(r"\d{1,4}/(?:19|20)\d{2}/[^\s,;:()]+|[^\W_]+(?:-[^\W_]+)*", re.UNICODE)


@dataclass
class SearchWeights:
    vector: float = 1.0
    # Đo trên Golden Dataset (eval/eval_retrieval.py), có rerank: khi luồng từ khóa còn là OR từng
    # âm tiết, trọng số 0,25 tốt hơn (CP@5 0,681 -> 0,744). Sau khi chuyển sang cụm hai âm tiết và
    # hiệu đính OCR, trọng số 1 tốt nhất: CP@5 0,789 (0,25) / 0,794 (0,5) / 0,798 (1). Không có
    # reranker thì retrieve() chỉ dùng vector (service.NO_RERANK_WEIGHTS).
    keyword: float = 1.0
    referenced: float = 1.0
    definition: float = 1.0
    candidates: int = 50  # số kết quả mỗi luồng trước khi hợp nhất


# Câu hỏi định nghĩa: "Ly hôn là gì", "Thế nào là tảo hôn", "Khái niệm người lao động". Đáp án nằm
# ở Điều "Giải thích từ ngữ" dưới dạng "14. Ly hôn là ...": một luồng riêng tìm đúng mẫu này. Đoạn
# định nghĩa ngắn và chung chung nên hay bị các Điều nói chi tiết về thuật ngữ (Điều 51, 55, 56 về
# ly hôn) đẩy ra khỏi 20 ứng viên (bộ hold-out HO-008).
_DEFINITION_RES = [
    re.compile(r"^(?:vậy\s+|cho hỏi\s+)?(?P<t>[^,?.:;]{2,60}?)\s+(?:là gì|là như thế nào|"
               r"được hiểu (?:là gì|là như thế nào|như thế nào)|có nghĩa là gì|nghĩa là gì)\b",
               re.I),
    re.compile(r"(?:thế nào là|thế nào được (?:coi|gọi|hiểu) là|khái niệm|định nghĩa)\s+"
               r"(?P<t>[^,?.:;]{2,60}?)\s*(?:$|[?,.:;]|\s+(?:theo|trong|là)\b)", re.I),
]  # fmt: skip


def definition_term(query: str) -> str | None:
    """Thuật ngữ được hỏi định nghĩa, viết thường; None nếu không phải câu hỏi định nghĩa."""
    for pattern in _DEFINITION_RES:
        m = pattern.search(query.strip())
        if m:
            term = re.sub(r"\s+", " ", m.group("t")).strip().lower()
            if 1 <= len(term.split()) <= 6:
                return term
    return None


def definition_regex(query: str) -> str:
    """Biểu thức chính quy (PostgreSQL) cho dòng định nghĩa "N. <thuật ngữ> là ..."; rỗng nếu
    không phải câu hỏi định nghĩa."""
    term = definition_term(query)
    if not term:
        return ""
    words = r"\s+".join(re.escape(w) for w in term.split())
    return r"(^|\n)\s*\d{1,3}\s*[.,]\s*" + words + r"\s+(là|được hiểu là)\s"


@dataclass
class FusedHit:
    chunk_id: str
    document_number: str
    document_title: str
    status: str
    effective_date: date | None
    expiry_date: date | None
    article: str | None
    clause: str | None
    point: str | None
    context_prefix: str
    content: str
    char_start: int
    char_end: int
    score: float
    vec_rank: int | None
    kw_rank: int | None
    ref_rank: int | None
    replaced_by: list[str] = field(default_factory=list)
    # ["repealed:168/2024/NĐ-CP"]: Điều/Khoản này (hoặc một phần) bị bãi bỏ / thay nội dung
    superseded_by: list[str] = field(default_factory=list)
    # Do reranker (Task 3.3) gán: điểm liên quan [0, 1] và thứ hạng trước khi rerank
    rerank_score: float | None = None
    hybrid_rank: int | None = None
    # Văn bản chứa đoạn: để giao diện mở nguyên văn (Task 4.3)
    document_id: str | None = None

    @property
    def citation(self) -> str:
        parts = [p for p in (self.article, self.clause, self.point) if p]
        return f"[{', '.join(parts) or 'Văn bản'} - {self.document_number}]"


@dataclass
class SearchResult:
    query: str
    plan: RetrievalPlan
    hits: list[FusedHit]


def tsquery_terms(query: str) -> str:
    """Biểu thức to_tsquery('simple', ...) theo **cụm hai âm tiết liền nhau**: ('đèn' <-> 'tín') |
    ('tín' <-> 'hiệu') | ... ; số hiệu văn bản giữ nguyên.

    Tiếng Việt viết theo âm tiết: OR từng âm tiết ('xe' | 'máy' | 'đèn'...) khớp hàng nghìn đoạn
    và đẩy đoạn có đúng cụm "đèn tín hiệu giao thông" xuống dưới (Golden Dataset, cấu hình có
    rerank: Context Precision@5 0,774 -> 0,789, Recall@5 0,894 -> 0,915 với cụm hai âm tiết).
    Câu chỉ có một âm tiết có nghĩa thì dùng âm tiết đó.
    """
    words = [w.lower() for w in _WORD_RE.findall(query)]
    terms: list[str] = []

    def quote(w: str) -> str:
        return "'" + w.replace("'", "''") + "'"

    for a, b in zip(words, words[1:], strict=False):
        if a in STOPWORDS or b in STOPWORDS or "/" in a or "/" in b:
            continue
        if (len(a) == 1 and not a.isdigit()) or (len(b) == 1 and not b.isdigit()):
            continue
        term = f"({quote(a)} <-> {quote(b)})"
        if term not in terms:
            terms.append(term)
    for w in words:
        if "/" in w and quote(w) not in terms:  # số hiệu văn bản: 168/2024/nđ-cp
            terms.append(quote(w))
    if not terms:  # không có cặp nào: OR các âm tiết có nghĩa
        for w in words:
            if w in STOPWORDS or (len(w) == 1 and not w.isdigit()):
                continue
            if quote(w) not in terms:
                terms.append(quote(w))
    return " | ".join(terms)


def _doc_filter(plan: RetrievalPlan, params: dict[str, Any]) -> str:
    """Điều kiện trên bảng legal_documents d theo kế hoạch truy xuất."""
    if plan.period:
        params["period_start"], params["period_end"] = plan.period
        # Có hiệu lực tại một thời điểm nào đó trong khoảng [start, end]
        scope = (
            "(coalesce(d.effective_date, d.issue_date) <= %(period_end)s"
            " AND (d.expiry_date IS NULL OR d.expiry_date > %(period_start)s))"
        )
    else:
        params["statuses"] = list(plan.statuses)
        scope = "d.status::text = ANY(%(statuses)s)"
    if plan.referenced:
        params["referenced"] = plan.referenced
        scope = f"({scope} OR d.document_number = ANY(%(referenced)s))"
    # Cấp đoạn: bỏ Điều/Khoản đã bị bãi bỏ / thay nội dung (VD: phần đường bộ của NĐ 100/2019 bị
    # NĐ 168/2024 bãi bỏ dù văn bản vẫn AMENDED). Câu hỏi so sánh thì giữ lại để đối chiếu.
    if plan.mode == "compare":
        params["cutoff"] = None
    elif plan.period:
        params["cutoff"] = plan.period[0]
    else:
        params["cutoff"] = date.today()
    return scope + _NOT_SUPERSEDED


_NOT_SUPERSEDED = """
    AND (%(cutoff)s::date IS NULL OR NOT EXISTS (
      SELECT 1 FROM superseded_provisions sp
      WHERE sp.target_number = d.document_number AND sp.article = c.article
        AND (sp.clause = '' OR sp.clause = c.clause) AND sp.effective_date <= %(cutoff)s::date))"""

_HYBRID_SQL = """
WITH vec AS (
  SELECT id, row_number() OVER (ORDER BY dist) AS rank FROM (
    SELECT c.id, c.embedding <=> %(qvec)s AS dist
    FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL AND {scope}
    ORDER BY dist LIMIT %(n)s
  ) s
),
kw AS (
  SELECT id, row_number() OVER (ORDER BY r DESC) AS rank FROM (
    SELECT c.id, ts_rank_cd(c.search_vector, q) AS r
    FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id
      CROSS JOIN to_tsquery('simple', %(tsq)s) q
    WHERE %(tsq)s <> '' AND c.search_vector @@ q AND {scope}
    ORDER BY r DESC LIMIT %(n)s
  ) s
),
ref AS (
  SELECT id, row_number() OVER (ORDER BY dist) AS rank FROM (
    SELECT c.id, c.embedding <=> %(qvec)s AS dist
    FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL AND d.document_number = ANY(%(ref_numbers)s)
    ORDER BY dist LIMIT %(n)s
  ) s
),
defn AS (
  SELECT id, row_number() OVER (ORDER BY len, id) AS rank FROM (
    SELECT c.id, length(c.content) AS len
    FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id
    WHERE %(def_re)s <> '' AND lower(c.content) ~ %(def_re)s AND {scope}
    LIMIT %(n)s
  ) s
),
fused AS (
  SELECT coalesce(v.id, k.id, r.id, df.id) AS id,
         coalesce(%(w_vec)s / (%(rrf_k)s + v.rank), 0)
       + coalesce(%(w_kw)s / (%(rrf_k)s + k.rank), 0)
       + coalesce(%(w_ref)s / (%(rrf_k)s + r.rank), 0)
       + coalesce(%(w_def)s / (%(rrf_k)s + df.rank), 0) AS score,
         v.rank AS vec_rank, k.rank AS kw_rank, r.rank AS ref_rank
  FROM vec v
  FULL OUTER JOIN kw k ON k.id = v.id
  FULL OUTER JOIN ref r ON r.id = coalesce(v.id, k.id)
  FULL OUTER JOIN defn df ON df.id = coalesce(v.id, k.id, r.id)
)
SELECT c.id, d.document_number, d.title, d.status::text, d.effective_date, d.expiry_date,
       c.article, c.clause, c.point, c.context_prefix, c.content, c.char_start, c.char_end,
       f.score, f.vec_rank, f.kw_rank, f.ref_rank,
       coalesce((SELECT array_agg(DISTINCT dr.source_number)
                 FROM document_relations dr
                 WHERE dr.target_number = d.document_number AND dr.relation_type = 'replaces'),
                '{{}}') AS replaced_by,
       coalesce((SELECT array_agg(DISTINCT sp.kind || ':' || sp.source_number)
                 FROM superseded_provisions sp
                 WHERE sp.target_number = d.document_number AND sp.article = c.article
                   AND (sp.clause = '' OR c.clause IS NULL OR sp.clause = c.clause)),
                '{{}}') AS superseded_by,
       d.id
FROM fused f
JOIN legal_chunks c ON c.id = f.id
JOIN legal_documents d ON d.id = c.document_id
ORDER BY f.score DESC, c.id
LIMIT %(top_k)s
"""


def resolve_named(conn: psycopg.Connection, plan: RetrievalPlan) -> None:
    """Quy 'Luật Đất đai 2013' về số hiệu: cùng loại, năm ban hành (hoặc năm trong số hiệu), tên."""
    for kind, name, year in plan.named:
        rows = conn.execute(
            r"""
            SELECT document_number FROM legal_documents
            WHERE (extract(year FROM issue_date) = %(y)s OR document_number LIKE %(ylike)s)
              AND title ~* %(kind)s AND (%(name)s = '' OR title ~* %(name)s)
            ORDER BY issue_date
            """,
            {
                "y": year,
                "ylike": f"%/{year}/%",
                "kind": fz(kind),
                "name": fz(name) if name else "",
            },
        ).fetchall()
        for (number,) in rows:
            if number not in plan.referenced:
                plan.referenced.append(number)
                plan.reasons.append(f"'{kind} {name} {year}' -> {number}")


def hybrid_search(
    conn: psycopg.Connection,
    query: str,
    query_vector: np.ndarray,
    *,
    top_k: int = 20,
    plan: RetrievalPlan | None = None,
    weights: SearchWeights | None = None,
    ef_search: int = 100,
) -> SearchResult:
    plan = plan or route(query)
    weights = weights or SearchWeights()
    resolve_named(conn, plan)
    plan.referenced = [normalize_number(n) for n in plan.referenced]

    register_vector(conn)
    conn.execute(f"SET hnsw.ef_search = {int(ef_search)}")
    # Lọc theo phạm vi văn bản sau khi quét HNSW -> cho phép quét tiếp để vẫn đủ N kết quả
    conn.execute("SET hnsw.iterative_scan = relaxed_order")

    params: dict[str, Any] = {
        "qvec": query_vector,
        "tsq": tsquery_terms(query),
        "n": weights.candidates,
        "ref_numbers": plan.referenced,
        "w_vec": weights.vector,
        "w_kw": weights.keyword,
        "w_ref": weights.referenced if plan.referenced else 0.0,
        "def_re": definition_regex(query),
        "w_def": weights.definition,
        "rrf_k": float(RRF_K),
        "top_k": top_k,
    }
    sql = _HYBRID_SQL.format(scope=_doc_filter(plan, params))
    rows = conn.execute(sql, params).fetchall()
    hits = [
        FusedHit(
            chunk_id=str(r[0]),
            document_number=r[1],
            document_title=r[2],
            status=r[3],
            effective_date=r[4],
            expiry_date=r[5],
            article=r[6],
            clause=r[7],
            point=r[8],
            context_prefix=r[9],
            content=r[10],
            char_start=r[11],
            char_end=r[12],
            score=float(r[13]),
            vec_rank=r[14],
            kw_rank=r[15],
            ref_rank=r[16],
            replaced_by=list(r[17] or []),
            superseded_by=list(r[18] or []),
            document_id=str(r[19]),
        )
        for r in rows
    ]
    return SearchResult(query=query, plan=plan, hits=hits)
