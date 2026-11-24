"""Đọc Golden Dataset và các phép so khớp dùng chung cho các script đánh giá (Task 5.1–5.2)."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

GOLDEN_PATH = Path(__file__).with_name("golden.jsonl")


@dataclass
class Reference:
    document: str
    article: str
    clause: str | None = None


@dataclass
class GoldenItem:
    id: str
    domain: str
    difficulty: str
    type: str
    question: str
    reference_answer: str
    references: list[Reference]
    key_facts: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    expect_refusal: bool = False


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenItem]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        raw["references"] = [Reference(**r) for r in raw["references"]]
        items.append(GoldenItem(**raw))
    return items


def norm(text: str) -> str:
    """So khớp chữ: NFC, chữ thường, gộp khoảng trắng (văn bản OCR hay thừa/thiếu khoảng trắng)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).lower().strip()


def has_fact(text: str, fact: str) -> bool:
    """``fact`` có thể có nhiều cách viết, ngăn bởi ``|``."""
    t = norm(text)
    return any(norm(alt) in t for alt in fact.split("|"))


def matches(ref: Reference, document: str, article: str | None, clause: str | None) -> bool:
    """Đoạn (document, article, clause) có chứa căn cứ ``ref`` không.

    Khớp theo Điều; nếu căn cứ ghi cả Khoản thì đoạn phải là Khoản đó hoặc cả Điều (clause None).
    """
    if norm(document) != norm(ref.document) or not article or norm(article) != norm(ref.article):
        return False
    return ref.clause is None or clause is None or norm(clause) == norm(ref.clause)


_NEGATION_RE = re.compile(
    r"(không|chưa|chẳng|sai|không đúng|không chính xác|không có căn cứ|bác bỏ)[^.!?\n]{0,60}$"
)


_REFUTED_RE = re.compile(r"(là|thì)?\s*(không chính xác|không đúng|sai)")


def asserts(text: str, phrase: str) -> bool:
    """Câu trả lời có **khẳng định** ``phrase`` không: bỏ qua các lần xuất hiện trong câu phủ định
    ("không có căn cứ để khẳng định nữ đủ 16 tuổi là được kết hôn" không phải khẳng định)."""
    t = norm(text)
    for alt in phrase.split("|"):
        p = norm(alt)
        start = t.find(p)
        while start >= 0:
            after = t[start + len(p) : start + len(p) + 60].split(".")[0]
            if not _NEGATION_RE.search(t[max(0, start - 80) : start]) and not _REFUTED_RE.search(
                after
            ):
                return True
            start = t.find(p, start + 1)
    return False
