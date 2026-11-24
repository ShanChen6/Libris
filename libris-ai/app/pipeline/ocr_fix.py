"""Hiệu đính dấu thanh cho văn bản OCR bằng ngữ cảnh hai âm tiết.

Tesseract (vie) hay bỏ dấu thanh trên â/ê/ô: "đất" -> "đât", "điều" -> "điêu", "giấy" -> "giây".
Một âm tiết chỉ được thay bằng âm tiết **cùng mặt chữ, khác dấu** khi cặp âm tiết với từ đứng trước
hoặc sau có bằng chứng rõ trong văn bản sạch (không qua OCR) của kho, còn cặp gốc thì không:
"giây phép" (0 lần) -> "giấy phép" (hàng trăm lần). Không đụng tới chữ số, không đổi độ dài văn bản,
nên vị trí ký tự (char_start/char_end) của đoạn luật vẫn đúng.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
# Âm tiết, con số và dấu câu đều là một vị trí: "Phạt tiền từ 2.000.000 đồng" -> ngữ cảnh của "từ"
# là "tiền" và <số> (nếu bỏ qua con số, "từ" sẽ bị coi là đứng cạnh "đồng")
_TOKEN_RE = re.compile(r"[^\W\d_]+|\d[\d.,/]*|[^\w\s]", re.UNICODE)
COMMON = 20  # âm tiết xuất hiện >= 20 lần trong văn bản sạch: cần bằng chứng mạnh hơn mới sửa


def _tokens(text: str):
    """(start, end, token gốc, token chuẩn hóa): chữ -> chữ thường, số -> <số>, dấu câu -> <p>."""
    for m in _TOKEN_RE.finditer(text):
        t = m.group(0)
        key = t.lower() if t[0].isalpha() else ("<số>" if t[0].isdigit() else "<p>")
        yield m.start(), m.end(), t, key


_TONES = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}  # huyền, sắc, ngã, hỏi, nặng


def base(word: str) -> str:
    """Bỏ **dấu thanh**, giữ nguyên chữ cái (â, ê, ô, ư, ơ, ă, đ): 'điều' -> 'điêu', 'đất' -> 'đât'.

    OCR thường chỉ làm mất dấu thanh; không cho đổi mặt chữ ("dưỡng" không được thành "đường",
    "mức" không được thành "mục").
    """
    w = unicodedata.normalize("NFD", word.lower())
    return unicodedata.normalize("NFC", "".join(c for c in w if c not in _TONES))


@dataclass
class LanguageModel:
    """Thống kê âm tiết và cặp âm tiết của văn bản sạch."""

    unigrams: Counter = field(default_factory=Counter)
    bigrams: Counter = field(default_factory=Counter)
    by_base: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def from_texts(cls, texts) -> LanguageModel:
        lm = cls()
        for text in texts:
            keys = [k for *_, k in _tokens(unicodedata.normalize("NFC", text))]
            lm.unigrams.update(k for k in keys if k[0] != "<")
            lm.bigrams.update(zip(keys, keys[1:], strict=False))
        for w in lm.unigrams:
            lm.by_base[base(w)].add(w)
        return lm


def _match_case(src: str, dst: str) -> str:
    return "".join(d.upper() if s.isupper() else d for s, d in zip(src, dst, strict=True))


@dataclass
class FixReport:
    replaced: int = 0
    examples: Counter = field(default_factory=Counter)  # (gốc, sửa) -> số lần


def fix_text(
    text: str, lm: LanguageModel, *, min_support: int = 3, ratio: float = 8.0, alpha: float = 0.5
) -> tuple[str, FixReport]:
    """Trả về (văn bản đã hiệu đính, báo cáo). Độ dài văn bản không đổi.

    Điểm của một dạng ``c`` = (L + α)(R + α), với L, R là số lần cặp (từ trước, c) và (c, từ sau)
    xuất hiện trong văn bản sạch: phải hợp với **cả hai phía** ("80.000.000 đông đối với" -> "đồng",
    không phải "động" dù "lao động đối với" rất hay gặp). Chỉ sửa khi dạng gốc chưa từng gặp trong
    ngữ cảnh đó, dạng mới có ít nhất ``min_support`` lần và điểm gấp ``ratio`` lần dạng khác.
    """
    text = unicodedata.normalize("NFC", text)
    tokens = list(_tokens(text))
    keys = [k for *_, k in tokens]
    report = FixReport()
    out = list(text)
    # Hai lượt: lượt sau dùng từ đã sửa ở lượt trước làm ngữ cảnh ("điêu khiên" -> "điều khiển")
    for _ in range(2):
        for i, w in enumerate(keys):
            if w[0] == "<":
                continue
            candidates = [c for c in lm.by_base.get(base(w), ()) if c != w and len(c) == len(w)]
            if not candidates:
                continue
            prev = keys[i - 1] if i else None
            nxt = keys[i + 1] if i + 1 < len(keys) else None

            def sides(c: str, prev=prev, nxt=nxt) -> tuple[int, int]:
                return (lm.bigrams[(prev, c)] if prev else 0, lm.bigrams[(c, nxt)] if nxt else 0)

            def score(c: str) -> float:
                left, right = sides(c)
                return (left + alpha) * (right + alpha)

            if sum(sides(w)) > 0:
                continue  # dạng gốc đã gặp trong ngữ cảnh này ở văn bản sạch: giữ nguyên
            ranked = sorted(candidates, key=score, reverse=True)
            best = ranked[0]
            rival = max(score(w), score(ranked[1]) if len(ranked) > 1 else 0.0)
            left, right = sides(best)
            common = lm.unigrams[w] >= COMMON  # "từ", "giả": cần bằng chứng từ cả hai phía
            if (
                left + right >= min_support
                and score(best) >= ratio * rival
                and (not common or ((prev is None or left > 0) and (nxt is None or right > 0)))
            ):
                start, end, original, _ = tokens[i]
                fixed = _match_case(original, best)
                out[start:end] = fixed
                keys[i] = best
                tokens[i] = (start, end, fixed, best)
                report.replaced += 1
                report.examples[(original.lower(), best)] += 1
    return "".join(out), report


def clean_corpus_model(conn) -> LanguageModel:
    """Mô hình ngôn ngữ từ các văn bản không qua OCR (``needs_review = false``) trong kho."""
    rows = conn.execute("SELECT full_text FROM legal_documents WHERE NOT needs_review").fetchall()
    return LanguageModel.from_texts(r[0] for r in rows)


def fix_documents(
    conninfo: str, document_numbers: list[str] | None = None, *, dry_run: bool = False
) -> list[tuple[str, int]]:
    """Hiệu đính nguyên văn các văn bản OCR trong DB; trả về [(số hiệu, số chỗ đã sửa)].

    Sau đó cần cắt đoạn và sinh embedding lại cho các văn bản này (``chunk`` + ``embed``).
    """
    import psycopg
    from psycopg.types.json import Jsonb

    out: list[tuple[str, int]] = []
    with psycopg.connect(conninfo) as conn:
        lm = clean_corpus_model(conn)
        rows = conn.execute(
            "SELECT id, document_number, full_text FROM legal_documents WHERE needs_review"
            " AND (%(nums)s::text[] IS NULL OR document_number = ANY(%(nums)s))"
            " ORDER BY document_number",
            {"nums": document_numbers},
        ).fetchall()
        for doc_id, number, text in rows:
            fixed, report = fix_text(text, lm)
            out.append((number, report.replaced))
            if report.replaced and not dry_run:
                conn.execute(
                    "UPDATE legal_documents SET full_text = %s,"
                    " metadata = metadata || %s WHERE id = %s",
                    (fixed, Jsonb({"ocr_corrections": report.replaced}), doc_id),
                )
        conn.commit()
    return out
