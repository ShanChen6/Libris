"""Sinh eval/synthetic.jsonl – bộ câu hỏi tự động đo khả năng **tìm đúng đoạn luật** trên diện rộng.

Golden Dataset (100 câu) và hold-out (20 câu) do người soạn và đã được dùng khi tinh chỉnh, nên con
số đo trên đó có thể "đẹp" hơn thực tế. Bộ này lấy ngẫu nhiên các đoạn luật còn hiệu lực trong kho,
**không trùng Điều** với hai bộ kia, rồi nhờ LLM viết cho mỗi đoạn một câu hỏi đời thường mà đoạn đó
trả lời được. Đáp án = chính đoạn đó (văn bản + Điều + Khoản), nên chấm tự động được.

Giới hạn: câu hỏi do LLM viết thường dùng lại từ ngữ của văn bản (dễ hơn câu hỏi thật), và đôi khi
nhiều đoạn khác cũng trả lời được. Prompt yêu cầu diễn đạt lại bằng lời thường; ``lexical_overlap``
trong kết quả cho biết mức trùng từ để đọc con số cho đúng. Chỉ dùng để đo, không để tinh chỉnh.

    uv run python eval/build_synthetic.py --count 200
    uv run python eval/eval_retrieval.py --dataset eval/synthetic.jsonl \\
        --configs hybrid_kw1_rerank20
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from golden import load_golden  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.generation.llm import LLMError, Message, get_llm  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "synthetic.jsonl"
BATCH = 5

DOMAINS = {
    "168/2024/NĐ-CP": "giao_thong", "36/2024/QH15": "giao_thong", "100/2019/NĐ-CP": "giao_thong",
    "45/2019/QH14": "lao_dong", "145/2020/NĐ-CP": "lao_dong", "12/2022/NĐ-CP": "lao_dong",
    "31/2024/QH15": "dat_dai", "43/2024/QH15": "dat_dai", "101/2024/NĐ-CP": "dat_dai",
    "102/2024/NĐ-CP": "dat_dai", "88/2024/NĐ-CP": "dat_dai", "123/2024/NĐ-CP": "dat_dai",
    "52/2014/QH13": "hon_nhan", "126/2014/NĐ-CP": "hon_nhan",
}  # fmt: skip

PROMPT = """Bạn soạn câu hỏi kiểm tra cho một hệ thống tra cứu pháp luật Việt Nam.
Với MỖI đoạn luật dưới đây, viết đúng MỘT câu hỏi mà một người dân bình thường có thể hỏi và chính
đoạn luật đó trả lời được. Yêu cầu:
- Diễn đạt bằng lời thường hoặc mô tả một tình huống cụ thể; KHÔNG chép nguyên cụm từ dài của văn
  bản (không quá 3 từ liền nhau giống văn bản), không nêu số hiệu văn bản, số Điều, số Khoản.
- Câu hỏi phải đủ cụ thể để chỉ đoạn này (hoặc rất ít đoạn khác) trả lời được.
- Nếu đoạn chỉ là tiêu đề, danh mục, quy định về thủ tục nội bộ cơ quan nhà nước hoặc không có gì
  để một người dân hỏi thì đặt "skip": true.
Trả về JSON: {"items": [{"id": "<id của đoạn>", "question": "<câu hỏi>", "skip": false}, ...]}

"""


def candidates(conn, excluded: set[tuple[str, str]]) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.id::text, d.document_number, c.article, c.clause, c.content
        FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id
        WHERE d.status IN ('ACTIVE', 'AMENDED') AND c.article IS NOT NULL
          AND length(c.content) BETWEEN 200 AND 2500
        ORDER BY c.id
        """
    ).fetchall()
    out = []
    for chunk_id, number, article, clause, content in rows:
        if (number, article) in excluded or number not in DOMAINS:
            continue
        out.append(
            {"chunk_id": chunk_id, "document": number, "article": article, "clause": clause,
             "content": content}
        )  # fmt: skip
    return out


def sample(chunks: list[dict], count: int, seed: int) -> list[dict]:
    """Lấy mẫu theo văn bản (căn bậc hai số đoạn) để văn bản dài không lấn át, mỗi Điều tối đa 1."""
    rng = random.Random(seed)
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_doc[c["document"]].append(c)
    weights = {d: len(v) ** 0.5 for d, v in by_doc.items()}
    total = sum(weights.values())
    picked: list[dict] = []
    for doc, items in sorted(by_doc.items()):
        rng.shuffle(items)
        quota = max(1, round(count * weights[doc] / total))
        seen: set[str] = set()
        for c in items:
            if c["article"] in seen:
                continue
            seen.add(c["article"])
            picked.append(c)
            if len(seen) >= quota:
                break
    rng.shuffle(picked)
    return picked[: int(count * 1.25)]  # dư ra cho các đoạn bị "skip"


def ask(llm, batch: list[dict]) -> dict[str, str]:
    body = "\n\n".join(
        f'<doan id="{i}">\n{c["content"][:1800]}\n</doan>' for i, c in enumerate(batch)
    )
    for attempt in range(3):
        try:
            text = llm.complete([Message("user", PROMPT + body)], json_mode=True).text
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()))
            return {
                str(x["id"]): x["question"].strip()
                for x in data.get("items", [])
                if not x.get("skip") and x.get("question")
            }
        except (LLMError, json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"  lỗi ({exc}); thử lại", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sleep", type=float, default=4.0)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--resume", action="store_true", help="giữ các câu đã có trong --out")
    args = parser.parse_args()

    excluded = {
        (r.document, r.article)
        for path in (ROOT / "golden.jsonl", ROOT / "holdout.jsonl")
        for item in load_golden(path)
        for r in item.references
    }
    with psycopg.connect(get_settings().database_url) as conn:
        chunks = sample(candidates(conn, excluded), args.count, args.seed)
    llm = get_llm()
    items = []
    if args.resume and args.out.exists():
        items = [json.loads(line) for line in args.out.read_text().splitlines() if line.strip()]
        done = {tuple(x["references"][0].values()) for x in items}
        chunks = [c for c in chunks if (c["document"], c["article"], c["clause"]) not in done]
    overlap: list[float] = []
    for start in range(0, len(chunks), BATCH):
        if len(items) >= args.count:
            break
        batch = chunks[start : start + BATCH]
        questions = ask(llm, batch)
        for i, c in enumerate(batch):
            q = questions.get(str(i))
            if not q or len(items) >= args.count:
                continue
            overlap.append(lexical_overlap(q, c["content"]))
            items.append(
                {
                    "id": f"SY-{len(items) + 1:03d}",
                    "domain": DOMAINS[c["document"]],
                    "difficulty": "synthetic",
                    "type": "synthetic",
                    "question": q,
                    "reference_answer": re.sub(r"\s+", " ", c["content"])[:400],
                    "references": [
                        {"document": c["document"], "article": c["article"], "clause": c["clause"]}
                    ],
                    "key_facts": [],
                    "forbidden": [],
                    "expect_refusal": False,
                }
            )
        # Ghi sau mỗi lượt: bị ngắt giữa chừng (hết quota) vẫn giữ được phần đã sinh
        args.out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
        print(f"{len(items)}/{args.count}", flush=True)
        time.sleep(args.sleep)
    print(f"Đã ghi {len(items)} câu vào {args.out}")
    if overlap:
        print(f"lexical_overlap trung bình: {sum(overlap) / len(overlap):.2f}")


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = re.findall(r"[^\W\d_]+", text.lower())
    return set(zip(words, words[1:], strict=False))


def lexical_overlap(question: str, passage: str) -> float:
    """Tỷ lệ cặp từ liền nhau của câu hỏi có trong đoạn luật (0 = diễn đạt lại hoàn toàn)."""
    q = _bigrams(question)
    return len(q & _bigrams(passage)) / len(q) if q else 0.0


if __name__ == "__main__":
    main()
