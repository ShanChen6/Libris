"""Đối tượng giả dùng trong test."""

import hashlib

import numpy as np

DIM = 1024


class FakeEmbedder:
    """Băm từ vào vector 1024 chiều: văn bản chung nhiều từ thì gần nhau (đủ để kiểm tra luồng)."""

    dim = DIM
    max_seq_length = 64

    def __init__(self) -> None:
        self.calls = 0

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(DIM, dtype=np.float32)
        for word in text.lower().split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1
        return v / (np.linalg.norm(v) or 1)

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        return np.stack([self._vec(t) for t in texts])

    def count_tokens(self, texts: list[str]) -> list[int]:
        return [len(t.split()) for t in texts]


class FakeReranker:
    """Điểm = tỷ lệ từ của câu hỏi xuất hiện trong đoạn (đủ để kiểm tra luồng rerank)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def score(self, query: str, passages: list[str]) -> np.ndarray:
        self.calls.append((query, len(passages)))
        words = set(query.lower().split())
        return np.array(
            [len(words & set(p.lower().split())) / max(len(words), 1) for p in passages],
            dtype=np.float32,
        )
