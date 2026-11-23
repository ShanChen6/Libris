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
