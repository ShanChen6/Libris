"""Semantic Cache (Task 5.3): câu hỏi giống nghĩa câu đã trả lời -> trả lại ngay từ Redis.

Lưu trong Redis 8 bằng Vector Set (``VADD``/``VSIM``, có sẵn trong Redis 8, không cần module):

- ``{prefix}:vs:{scope}``: vector set các câu hỏi (embedding bge-m3 của câu gốc);
- ``{prefix}:entry:{id}``: câu trả lời (JSON), có TTL.

``scope`` gồm tùy chọn của câu hỏi (xem cả văn bản hết hiệu lực, mốc thời gian), **ngày hiện tại**
và **phiên bản kho dữ liệu**: nạp/xóa văn bản hay sang ngày mới (văn bản có thể bắt đầu/hết hiệu
lực) đều chuyển sang scope mới, nên không bao giờ trả câu trả lời cũ cho kho đã đổi.

Trúng cache khi cả hai điều kiện đúng (ngưỡng chọn bằng eval/calibrate_cache.py):

1. cosine ≥ ``threshold`` (mặc định 0,95);
2. cùng **chữ ký**: cùng các con số (mức tiền, tốc độ, năm, số hiệu văn bản) và cùng các cụm phân
   biệt (loại xe, nam/nữ, loại ngày làm thêm, loại đất...). Embedding coi "xe máy vượt đèn đỏ" và
   "ô tô vượt đèn đỏ" giống nhau 0,957 nhưng mức phạt khác hẳn, nên chỉ dùng ngưỡng là không đủ.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Mỗi nhóm: các cụm loại trừ nhau -> nhãn chuẩn. Hai câu chứa nhãn khác nhau trong cùng nhóm thì
# không bao giờ dùng chung câu trả lời.
_GROUPS: dict[str, list[tuple[str, str]]] = {
    "vehicle": [
        (r"xe (?:gắn )?máy|mô tô|xe máy điện", "moto"),
        (r"ô tô|xe hơi|xe con|xe tải|xe khách|xe buýt|xe container|xe đầu kéo", "car"),
        (r"xe đạp", "bike"),
        (r"máy kéo|xe máy chuyên dùng", "special"),
    ],
    "gender": [(r"\bnam\b|đàn ông|con trai|người chồng", "male"),
               (r"\bnữ\b|phụ nữ|con gái|người vợ", "female")],
    "day": [
        (r"ngày thường", "weekday"),
        (r"ngày nghỉ hằng tuần|chủ nhật|cuối tuần", "weekly_rest"),
        (r"ngày lễ|\btết\b", "holiday"),
        (r"ban đêm|ca đêm", "night"),
    ],
    "land": [
        (r"phi nông nghiệp", "non_agri"),
        (r"(?<!phi )nông nghiệp", "agri"),
        (r"đất ở", "residential"),
        (r"đất rừng", "forest"),
    ],
    "contract": [
        (r"không xác định thời hạn", "indefinite"),
        (r"(?<!không )xác định thời hạn", "fixed"),
    ],
    "party": [(r"người lao động|nhân viên", "employee"),
              (r"người sử dụng lao động|công ty|doanh nghiệp", "employer")],
    "era": [(r"\bcũ\b|trước đây|hết hiệu lực", "old"), (r"so sánh|khác nhau", "compare")],
}  # fmt: skip
_NUMBER_RE = re.compile(r"\d+(?:[.,/]\d+)*")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).lower().strip()


def signature(question: str) -> str:
    """Những chi tiết phải trùng khớp tuyệt đối thì mới dùng chung câu trả lời."""
    q = _norm(question)
    numbers = sorted({n.replace(",", ".") for n in _NUMBER_RE.findall(q)})
    parts = ["num=" + ",".join(numbers)]
    for group, options in _GROUPS.items():
        labels = sorted({label for pattern, label in options if re.search(pattern, q)})
        if labels:
            parts.append(f"{group}={'+'.join(labels)}")
    return ";".join(parts)


@dataclass
class CacheHit:
    payload: dict[str, Any]
    similarity: float  # cosine
    question: str  # câu hỏi đã được trả lời trước đó


class SemanticCache:
    def __init__(
        self, redis, *, threshold: float = 0.95, ttl: int = 86_400, prefix: str = "libris:qa"
    ) -> None:
        self.redis = redis
        self.threshold = threshold
        self.ttl = ttl
        self.prefix = prefix

    def _vset(self, scope: str) -> str:
        return f"{self.prefix}:vs:{scope}"

    def _entry(self, entry_id: str) -> str:
        return f"{self.prefix}:entry:{entry_id}"

    @staticmethod
    def scope(*parts: Any) -> str:
        raw = json.dumps(parts, ensure_ascii=False, default=str, sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def lookup(self, question: str, vector: np.ndarray, scope: str) -> CacheHit | None:
        key = self._vset(scope)
        try:
            if not self.redis.exists(key):
                return None
            found = self.redis.vset().vsim(key, _vec(vector), with_scores=True, count=5) or {}
            sig = signature(question)
            for element, score in found.items():
                cosine = 2 * float(score) - 1  # VSIM trả (1 + cosine) / 2
                if cosine < self.threshold:
                    break  # kết quả đã xếp giảm dần
                entry_id = element.decode() if isinstance(element, bytes) else str(element)
                raw = self.redis.get(self._entry(entry_id))
                if raw is None:  # hết TTL: dọn khỏi vector set
                    self.redis.vset().vrem(key, entry_id)
                    continue
                data = json.loads(raw)
                if data["signature"] != sig:
                    continue
                return CacheHit(data["payload"], cosine, data["question"])
        except Exception:  # noqa: BLE001 – cache hỏng không được làm hỏng việc trả lời
            log.warning("Không đọc được semantic cache", exc_info=True)
        return None

    def store(self, question: str, vector: np.ndarray, scope: str, payload: dict) -> None:
        entry_id = uuid.uuid4().hex
        data = {"question": question, "signature": signature(question), "payload": payload}
        key = self._vset(scope)
        try:
            pipe = self.redis.pipeline()
            pipe.set(self._entry(entry_id), json.dumps(data, ensure_ascii=False), ex=self.ttl)
            pipe.execute()
            self.redis.vset().vadd(key, _vec(vector), entry_id)
            self.redis.expire(key, self.ttl)
        except Exception:  # noqa: BLE001
            log.warning("Không ghi được semantic cache", exc_info=True)


def _vec(vector: np.ndarray) -> list[float]:
    return [float(x) for x in np.asarray(vector, dtype=np.float32).ravel()]


def corpus_version(conn) -> str:
    """Đổi mỗi khi văn bản được nạp, sửa, xóa hoặc đoạn luật được sinh lại embedding."""
    row = conn.execute(
        "SELECT (SELECT count(*) FROM legal_documents),"
        " (SELECT max(updated_at) FROM legal_documents),"
        " (SELECT count(*) FROM legal_chunks WHERE embedding IS NOT NULL),"
        " (SELECT count(*) FROM superseded_provisions),"
        " (SELECT count(*) FROM document_relations)"
    ).fetchone()
    return hashlib.sha1(repr(row).encode()).hexdigest()[:12]


_cache: SemanticCache | None = None


def get_cache() -> SemanticCache | None:
    """Cache dùng chung; None nếu tắt hoặc không kết nối được Redis (vẫn trả lời bình thường)."""
    global _cache
    from app.core.config import get_settings

    s = get_settings()
    if not s.semantic_cache_enabled:
        return None
    if _cache is None:
        import redis

        client = redis.Redis.from_url(s.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        try:
            client.ping()
        except Exception:  # noqa: BLE001
            log.warning("Không kết nối được Redis (%s): tắt semantic cache", s.redis_url)
            return None
        _cache = SemanticCache(
            client, threshold=s.semantic_cache_threshold, ttl=s.semantic_cache_ttl
        )
    return _cache
