"""Task 3.3 – Tái xếp hạng bằng cross-encoder (BAAI/bge-reranker-v2-m3).

Hybrid Search (bi-encoder + BM25) nhanh nhưng chỉ so khớp gần đúng. Cross-encoder đọc đồng thời
câu hỏi và từng đoạn luật nên đánh giá mức độ liên quan chính xác hơn nhiều, đổi lại chậm hơn;
vì vậy chỉ chấm lại Top N ứng viên (mặc định 20) và giữ Top 5 đưa cho LLM.

Điểm trả về nằm trong [0, 1] (sigmoid của logit) – dùng được làm ngưỡng "không có điều luật đủ
liên quan" để từ chối trả lời (Task 3.4).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

import numpy as np

from app.core.config import get_settings
from app.pipeline.embedding import chunk_text
from app.retrieval.hybrid import FusedHit

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

log = logging.getLogger(__name__)


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> np.ndarray:
        """Điểm liên quan trong [0, 1] cho từng đoạn, cùng thứ tự với ``passages``."""
        ...


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        max_length: int = 1024,
        batch_size: int = 10,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            log.info("Tải reranker %s (%s)...", self.model_name, self.device)
            self._model = CrossEncoder(
                self.model_name, device=self.device, max_length=self.max_length
            )
        return self._model

    def score(self, query: str, passages: list[str]) -> np.ndarray:
        if not passages:
            return np.zeros(0, dtype=np.float32)
        scores = self.model.predict(
            [(query, p) for p in passages],
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = np.asarray(scores, dtype=np.float32)
        # sentence-transformers đã áp sigmoid cho mô hình 1 nhãn; phòng trường hợp trả logit
        if scores.min() < 0 or scores.max() > 1:
            scores = 1 / (1 + np.exp(-scores))
        return scores


@lru_cache
def get_reranker() -> CrossEncoderReranker | None:
    """Reranker dùng chung cho cả tiến trình (mô hình chỉ tải một lần).

    ``RERANKER_ENABLED=false``: không tải mô hình (tiết kiệm ~2,3 GB RAM khi triển khai trên máy
    nhỏ); truy xuất chỉ dùng Hybrid Search, chất lượng giảm (Context Precision@5 0,809 -> 0,661 trên
    Golden Dataset) và không còn bước từ chối trước khi gọi LLM theo điểm rerank.
    """
    s = get_settings()
    if not s.reranker_enabled:
        return None
    return CrossEncoderReranker(
        s.reranker_model,
        device=s.reranker_device,
        max_length=s.reranker_max_length,
        batch_size=s.reranker_batch_size,
    )


def rerank(
    query: str, hits: list[FusedHit], reranker: Reranker, *, top_n: int = 5
) -> list[FusedHit]:
    """Chấm lại ``hits`` và trả về ``top_n`` đoạn liên quan nhất (giữ thứ hạng Hybrid cũ)."""
    if not hits:
        return []
    scores = reranker.score(query, [chunk_text(h.context_prefix, h.content) for h in hits])
    rescored = [
        replace(h, rerank_score=float(s), hybrid_rank=i)
        for i, (h, s) in enumerate(zip(hits, scores, strict=True), 1)
    ]
    rescored.sort(key=lambda h: (-(h.rerank_score or 0.0), h.hybrid_rank or 0))
    return rescored[:top_n]
