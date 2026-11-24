"""Hiệu đính dấu thanh cho văn bản OCR bằng ngữ cảnh hai âm tiết.

Tesseract (vie) hay bỏ dấu thanh trên â/ê/ô: "đất" -> "đât", "điều" -> "điêu", "giấy" -> "giây".
Một âm tiết chỉ được thay bằng âm tiết **cùng mặt chữ, khác dấu** khi cặp âm tiết với từ đứng trước
hoặc sau có bằng chứng rõ trong văn bản sạch (không qua OCR) của kho, còn cặp gốc thì không:
"giây phép" (0 lần) -> "giấy phép" (hàng trăm lần). Không đụng tới chữ số, không đổi độ dài văn bản,
nên vị trí ký tự (char_start/char_end) của đoạn luật vẫn đúng.

Ngoài dấu thanh, ``fix_ocr`` còn sửa ba loại lỗi mặt chữ (cũng không đổi độ dài văn bản):

- ``fix_confusions``: ký tự hay bị đọc nhầm trong một từ không có trong từ vựng sạch ("1y hôn" ->
  "ly hôn", "g1ao" -> "giao", "jy hôn" -> "ly hôn"), chỉ khi ngữ cảnh hai phía xác nhận.
- ``fix_point_labels``: nhãn Điểm bị đọc sai trong một dãy Điểm ("a) b) ©) d)" -> "c)",
  "8)" -> "g)", "¡)" -> "i)"), dựa vào thứ tự chữ cái của các Điểm liền trước.
- ``fix_clause_numbers``: số Khoản bị đọc sai và dính vào Khoản trước
  ("...mục đích khác. l6. Thành viên" -> xuống dòng + "16."), khi đúng bằng số Khoản kế tiếp.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.pipeline.vn import POINT_LETTERS

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

            # Dấu câu không phải bằng chứng: "b) Tảo hôn" không được thành "b) Tạo hôn" chỉ vì
            # trong văn bản sạch hay gặp ") Tạo"
            if prev == "<p>":
                prev = None
            if nxt == "<p>":
                nxt = None

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


# Ký tự OCR hay đọc nhầm -> các chữ cái có thể là bản gốc
_CONFUSABLE = {
    "1": "lit", "0": "oôơ", "5": "s", "8": "g", "6": "óbở", "j": "li", "ø": "go", "š": "s",
    "ñ": "n", "í": "i", "ì": "i",
}  # fmt: skip
_WORDISH_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE_START_RE = re.compile(r"(?:^|\n)\s*(?:\d{1,3}\s*[.,]|[a-zđ]\))\s*$")


def _variants(word: str, limit: int = 2):
    """Các cách thay tối đa ``limit`` ký tự dễ nhầm trong ``word`` (cùng độ dài)."""
    spots = [i for i, ch in enumerate(word) if ch in _CONFUSABLE]
    if not spots or len(spots) > limit:
        return

    def expand(i: int, current: str):
        if i == len(spots):
            yield current
            return
        pos = spots[i]
        for repl in _CONFUSABLE[current[pos]] + current[pos]:
            yield from expand(i + 1, current[:pos] + repl + current[pos + 1 :])

    for v in expand(0, word):
        if v != word:
            yield v


_VOWELS = set("aăâeêioôơuưy")
_ROMAN_RE = re.compile(r"[ivxlc]+")


def _syllable(word: str) -> bool:
    """Có dáng một âm tiết tiếng Việt: chỉ chữ cái, có nguyên âm, không phải số La Mã."""
    return (
        word.isalpha()
        and any(base(c) in _VOWELS or unicodedata.normalize("NFD", c)[0] in _VOWELS for c in word)
        and not _ROMAN_RE.fullmatch(word)
    )


def fix_confusions(
    text: str, lm: LanguageModel, *, min_support: int = 3, ratio: float = 8.0, alpha: float = 0.5
) -> tuple[str, FixReport]:
    """Sửa từ chứa ký tự dễ nhầm ("1y", "g1ao", "jy") thành từ có trong văn bản sạch.

    Chỉ xét từ không có trong từ vựng sạch (hoặc lẫn chữ số với chữ cái); dạng mới phải có trong
    từ vựng và được ngữ cảnh hai phía xác nhận như ``fix_text``. Số thuần túy không bị đụng tới.
    """
    text = unicodedata.normalize("NFC", text)
    report = FixReport()
    words = list(_WORDISH_RE.finditer(text))
    out = list(text)

    def key(m: re.Match | None) -> str | None:
        if m is None:
            return None
        w = m.group(0).lower()
        return "<số>" if w.isdigit() else w

    for i, m in enumerate(words):
        w = m.group(0).lower()
        if w.isdigit() or (w in lm.unigrams and not any(c.isdigit() for c in w)):
            continue
        if re.fullmatch(r"\d+[abcdđ]", w):
            continue  # "khoản 8a", "Điều 10a": số hiệu hợp lệ
        if not any(c.isalpha() for c in w):
            continue
        candidates = [v for v in _variants(w) if _syllable(v) and v in lm.unigrams]
        if not candidates:
            continue
        # Ngữ cảnh chỉ tính khi giữa hai từ chỉ có khoảng trắng
        prev = words[i - 1] if i else None
        nxt = words[i + 1] if i + 1 < len(words) else None
        if prev is not None and text[prev.end() : m.start()].strip():
            prev = None
        if nxt is not None and text[m.end() : nxt.start()].strip():
            nxt = None
        pk, nk = key(prev), key(nxt)

        def sides(c: str, pk=pk, nk=nk) -> tuple[int, int]:
            return (lm.bigrams[(pk, c)] if pk else 0, lm.bigrams[(c, nk)] if nk else 0)

        def score(c: str) -> float:
            left, right = sides(c)
            return (left + alpha) * (right + alpha)

        ranked = sorted(candidates, key=score, reverse=True)
        best = ranked[0]
        left, right = sides(best)
        rival = score(ranked[1]) if len(ranked) > 1 else alpha * alpha
        if left + right >= min_support and score(best) >= ratio * rival:
            original = m.group(0)
            fixed = "".join(
                d.upper() if s.isupper() else d for s, d in zip(original, best, strict=True)
            )
            if _SENTENCE_START_RE.search(text, 0, m.start()):
                fixed = fixed[0].upper() + fixed[1:]  # "14. 1y hôn" -> "14. Ly hôn"
            out[m.start() : m.end()] = fixed
            report.replaced += 1
            report.examples[(original.lower(), best)] += 1
    return "".join(out), report


# Nhãn Điểm bị đọc sai -> các chữ cái mà nó có thể là
_POINT_CONFUSABLE = {
    "8": "g", "9": "g", "ø": "g", "Ø": "g", "q": "g",
    "¡": "il", "1": "il", "I": "il", "l": "il", "|": "il", "]": "il", "j": "il", "í": "i",
    "©": "ce", "€": "e", "@": "ae", "®": "e", "ẹ": "e", "o": "ce",
    "đ": "d", "ð": "dđ", "Đ": "dđ", "D": "dđ",
}  # fmt: skip
_POINT_LINE_RE = re.compile(r"^(\s*)(\S)\)(?=\s)", re.MULTILINE)
_CLAUSE_LINE_RE = re.compile(r"^\s*(?:\d{1,3}\s*[.,]\s|Điều\s+\d)")


def fix_point_labels(text: str) -> tuple[str, FixReport]:
    """Sửa nhãn Điểm trong dãy a), b), c)...: nhãn sai được thay bằng chữ cái kế tiếp mong đợi
    khi nó nằm trong bảng ký tự dễ nhầm của chữ cái đó và Điểm liền trước khớp thứ tự.

    "đ)" ngay sau "c)" chỉ được sửa thành "d)" khi Điểm kế tiếp là "đ)" hoặc "e)" (nếu không,
    có thể Điểm d thật sự bị OCR bỏ sót).
    """
    report = FixReport()
    out = list(text)
    last = -1  # vị trí trong POINT_LETTERS của Điểm gần nhất trong Khoản hiện tại
    lines = text.split("\n")
    offset = 0
    labels: list[tuple[int, str] | None] = []
    for line in lines:
        m = _POINT_LINE_RE.match(line)
        labels.append((offset + m.start(2), m.group(2)) if m else None)
        offset += len(line) + 1
    for i, line in enumerate(lines):
        if labels[i] is None:
            if _CLAUSE_LINE_RE.match(line):
                last = -1
            continue
        pos, label = labels[i]
        if label in POINT_LETTERS and POINT_LETTERS.index(label) > last:
            if label == "đ" and last >= 0 and POINT_LETTERS[last] == "c":
                nxt = next((lab for lab in labels[i + 1 : i + 3] if lab), None)
                if nxt and nxt[1] in ("đ", "e"):
                    out[pos] = "d"
                    report.replaced += 1
                    report.examples[("đ)", "d)")] += 1
                    last = POINT_LETTERS.index("d")
                    continue
            last = POINT_LETTERS.index(label)
            continue
        if last < 0 or last + 1 >= len(POINT_LETTERS):
            if label == "@" and last < 0:  # "@)" mở đầu dãy Điểm
                out[pos] = "a"
                report.replaced += 1
                report.examples[("@)", "a)")] += 1
                last = 0
            continue
        expected = POINT_LETTERS[last + 1]
        if expected in _POINT_CONFUSABLE.get(label, ""):
            out[pos] = expected
            report.replaced += 1
            report.examples[(f"{label})", f"{expected})")] += 1
            last += 1
    return "".join(out), report


_OCR_NUMBER = str.maketrans({"l": "1", "I": "1", "i": "1", "|": "1", "O": "0", "o": "0"})
_ARTICLE_HEAD_RE = re.compile(r"^\s*Điều\s+\d", re.MULTILINE)
_CLAUSE_HEAD_RE = re.compile(r"^\s*(\d{1,3})\s*\.\s", re.MULTILINE)
# Số Khoản đọc sai giữa dòng, ngay sau dấu kết câu: "... khác. l6. Thành viên"
_INLINE_CLAUSE_RE = re.compile(r"(?<=[.;]) ([\dlIi|Oo]{1,3})\. (?=[A-ZĐÀ-Ỹ])")
_LINE_CLAUSE_RE = re.compile(r"^(\s*)([\dlIi|Oo]{1,3})\. (?=\S)", re.MULTILINE)


def fix_clause_numbers(text: str) -> tuple[str, FixReport]:
    """Sửa số Khoản bị đọc sai ("l6." -> "16.") khi đúng bằng số Khoản kế tiếp trong Điều; số
    Khoản (kể cả đúng) bị dồn vào giữa dòng được đưa xuống dòng (thay khoảng trắng trước nó)."""
    report = FixReport()
    out = list(text)
    events: list[tuple[int, str, re.Match]] = []
    events += [(m.start(), "article", m) for m in _ARTICLE_HEAD_RE.finditer(text)]
    events += [(m.start(2), "line", m) for m in _LINE_CLAUSE_RE.finditer(text)]
    events += [(m.start(1), "inline", m) for m in _INLINE_CLAUSE_RE.finditer(text)]
    last = 0
    for _, kind, m in sorted(events, key=lambda e: e[0]):
        if kind == "article":
            last = 0
            continue
        group = 2 if kind == "line" else 1
        raw = m.group(group)
        number = raw.translate(_OCR_NUMBER)
        if not number.isdigit():
            continue
        value = int(number)
        if kind == "line" and raw.isdigit():
            last = value  # Khoản bình thường
            continue
        if not raw.isdigit() and not any(c.isdigit() for c in raw):
            continue  # "II." là số La Mã, không phải số Khoản đọc sai
        if kind == "line" and not text[m.end()].isupper():
            continue  # số Khoản đọc sai: chỉ nhận khi theo sau là chữ hoa
        if value != last + 1 or last == 0:
            continue
        start = m.start(group)
        if raw != number:
            out[start : start + len(raw)] = number
            report.examples[(raw, number)] += 1
        if kind == "inline":
            out[m.start()] = "\n"  # khoảng trắng trước số Khoản
            report.examples[("<giữa dòng>", "<xuống dòng>")] += 1
        report.replaced += 1
        last = value
    return "".join(out), report


def fix_ocr(
    text: str, lm: LanguageModel, vocab: LanguageModel | None = None
) -> tuple[str, FixReport]:
    """Toàn bộ các bước hiệu đính (độ dài văn bản không đổi).

    ``vocab``: mô hình cho bước ``fix_confusions``, có thể gồm cả văn bản OCR (kho sạch có thể
    thiếu hẳn một lĩnh vực, VD hôn nhân gia đình: "ly hôn" không xuất hiện). An toàn vì dạng sửa
    không chứa ký tự dễ nhầm và phải được ngữ cảnh xác nhận nhiều lần. Dấu thanh thì vẫn chỉ tin
    văn bản sạch (lỗi dấu thanh của OCR lặp lại có hệ thống).
    """
    total = FixReport()
    for step in (
        lambda t: fix_confusions(t, vocab or lm),
        fix_clause_numbers,
        fix_point_labels,
        lambda t: fix_text(t, lm),
    ):
        text, report = step(text)
        total.replaced += report.replaced
        total.examples.update(report.examples)
    return text, total


def clean_corpus_model(conn) -> LanguageModel:
    """Mô hình ngôn ngữ từ các văn bản không qua OCR (``needs_review = false``) trong kho."""
    rows = conn.execute("SELECT full_text FROM legal_documents WHERE NOT needs_review").fetchall()
    return LanguageModel.from_texts(r[0] for r in rows)


def corpus_model(conn) -> LanguageModel:
    """Mô hình từ toàn bộ kho (cả văn bản OCR), dùng cho ``fix_confusions``."""
    rows = conn.execute("SELECT full_text FROM legal_documents").fetchall()
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
        vocab = corpus_model(conn)
        rows = conn.execute(
            "SELECT id, document_number, full_text FROM legal_documents WHERE needs_review"
            " AND (%(nums)s::text[] IS NULL OR document_number = ANY(%(nums)s))"
            " ORDER BY document_number",
            {"nums": document_numbers},
        ).fetchall()
        for doc_id, number, text in rows:
            fixed, report = fix_ocr(text, lm, vocab)
            out.append((number, report.replaced))
            if report.replaced and not dry_run:
                conn.execute(
                    "UPDATE legal_documents SET full_text = %s,"
                    " metadata = metadata || %s WHERE id = %s",
                    (fixed, Jsonb({"ocr_corrections": report.replaced}), doc_id),
                )
        conn.commit()
    return out
