"""Kiểm tra Golden Dataset với kho dữ liệu (Task 5.1).

    uv run python eval/check_golden.py

- Mỗi căn cứ (văn bản + Điều [+ Khoản]) phải có ít nhất một đoạn trong legal_chunks.
- Mỗi key_fact phải xuất hiện trong nguyên văn các căn cứ hoặc trong đáp án chuẩn (key_fact như
  số hiệu văn bản thay thế chỉ có trong đáp án); key_fact không có trong căn cứ được báo để rà soát.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from golden import has_fact, load_golden, matches  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> int:
    items = load_golden()
    errors, notes = [], []
    ids = Counter(i.id for i in items)
    errors += [f"Trùng id {k}" for k, v in ids.items() if v > 1]
    with psycopg.connect(get_settings().database_url) as conn:
        rows = conn.execute(
            "SELECT d.document_number, c.article, c.clause, c.content FROM legal_chunks c "
            "JOIN legal_documents d ON d.id = c.document_id"
        ).fetchall()
    for item in items:
        if item.expect_refusal:
            if item.references:
                errors.append(f"{item.id}: câu cần từ chối không được có căn cứ")
            continue
        if not item.references or not item.reference_answer:
            errors.append(f"{item.id}: thiếu căn cứ hoặc đáp án")
        texts = []
        for ref in item.references:
            found = [r[3] for r in rows if matches(ref, r[0], r[1], r[2])]
            if not found:
                errors.append(f"{item.id}: không có đoạn nào cho {ref}")
            texts += found
        for fact in item.key_facts:
            if not has_fact(item.reference_answer, fact):
                errors.append(f"{item.id}: key_fact '{fact}' không có trong đáp án chuẩn")
            elif not any(has_fact(t, fact) for t in texts):
                notes.append(f"{item.id}: '{fact}' không có nguyên văn trong căn cứ (rà soát tay)")
    print(f"{len(items)} câu; {sum(len(i.references) for i in items)} căn cứ")
    print("\n".join(notes) or "Mọi key_fact đều có trong nguyên văn căn cứ")
    print("\n".join(errors) or "OK: mọi căn cứ đều có trong kho")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
