"""Task 2.2 – Sinh vector nhúng cho đoạn luật bằng BAAI/bge-m3 (dense, 1024 chiều)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

import numpy as np

from app.core.config import Settings, get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)


class Embedder(Protocol):
    dim: int
    max_seq_length: int

    def encode(self, texts: list[str]) -> np.ndarray:
        """Vector đã chuẩn hóa L2 (cosine similarity = tích vô hướng), shape (n, dim)."""
        ...

    def count_tokens(self, texts: list[str]) -> list[int]: ...


def chunk_text(context_prefix: str, content: str) -> str:
    """Văn bản đưa vào mô hình: tiền tố ngữ cảnh + nội dung, để vector 'hiểu' chủ thể áp dụng."""
    return f"{context_prefix}\n{content}"


class SentenceTransformerEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        max_seq_length: int = 1024,
        batch_size: int = 16,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_seq_length = max_seq_length
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            log.info("Tải mô hình %s (%s)...", self.model_name, self.device)
            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._model.max_seq_length = self.max_seq_length
        return self._model

    @property
    def dim(self) -> int:  # type: ignore[override]
        return int(self.model.get_sentence_embedding_dimension() or 0)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Số token thực (chưa cắt) – để phát hiện đoạn vượt max_seq_length."""
        ids = self.model.tokenizer(texts, add_special_tokens=True, truncation=False)["input_ids"]
        return [len(x) for x in ids]


@lru_cache
def get_embedder(settings: Settings | None = None) -> SentenceTransformerEmbedder:
    s = settings or get_settings()
    return SentenceTransformerEmbedder(
        s.embedding_model,
        device=s.embedding_device,
        max_seq_length=s.embedding_max_seq_length,
        batch_size=s.embedding_batch_size,
    )
