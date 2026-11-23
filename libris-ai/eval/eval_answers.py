"""Đánh giá câu trả lời trên Golden Dataset (Task 5.2).

    uv run python eval/eval_answers.py generate [--limit N]  # gọi LLM sinh câu trả lời
    uv run python eval/eval_answers.py ragas [--limit N]     # chấm RAGAS (LLM giám khảo)
    uv run python eval/eval_answers.py report                # tổng hợp chỉ số

`generate` và `ragas` lưu từng câu vào eval/results/*.jsonl và bỏ qua câu đã có, nên chạy lại để
làm tiếp khi bị ngắt (VD hết quota). Chỉ số tự động (không cần LLM):

- Đúng dữ kiện: câu trả lời chứa đủ mọi key_fact (con số, độ tuổi, số hiệu văn bản thay thế...).
- Trích dẫn: Precision = tỷ lệ trích dẫn đã xác minh trỏ đúng căn cứ; Recall = tỷ lệ căn cứ được
  trích dẫn.
- Từ chối: câu ngoài phạm vi phải bị từ chối; câu trả lời được mà bị từ chối là từ chối nhầm.
- Chèn lệnh: câu trả lời không được chứa nội dung trong `forbidden`.

RAGAS (LLM giám khảo, mặc định cùng Gemini với hệ thống – xem README về thiên lệch tự chấm):
- Faithfulness: tỷ lệ mệnh đề trong câu trả lời được các đoạn luật hỗ trợ.
- Answer Relevancy: độ tương đồng (bge-m3) giữa câu hỏi gốc và các câu hỏi LLM suy ngược từ câu
  trả lời.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")  # RAGAS mặc định gửi telemetry

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from golden import GoldenItem, has_fact, load_golden, matches  # noqa: E402

RESULTS = ROOT / "results"
ANSWERS = RESULTS / "answers.jsonl"
RAGAS = RESULTS / "ragas.jsonl"
REPORT = RESULTS / "answers_report.json"
_TAG_RE = re.compile(r"\[[^\[\]]*\d{1,4}/\d{4}/[^\]]*\]")


def _read(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {r["id"]: r for r in rows}


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


# ------------------------------------------------------------------------------- generate


def generate(items: list[GoldenItem], limit: int | None, pause: float) -> None:
    import psycopg
    from eval_retrieval import CachingReranker

    from app.core.config import get_settings
    from app.generation.answer import answer_question
    from app.generation.llm import LLMError, get_llm
    from app.generation.prompt import describe_validity
    from app.pipeline.embedding import get_embedder
    from app.retrieval.rerank import get_reranker
    from app.retrieval.service import make_plan

    settings = get_settings()
    done = _read(ANSWERS)
    todo = [i for i in items if i.id not in done][:limit]
    print(f"Đã có {len(done)} câu trả lời; sinh thêm {len(todo)}")
    embedder, reranker, llm = get_embedder(), CachingReranker(get_reranker()), get_llm()
    with psycopg.connect(settings.database_url) as conn:
        for n, item in enumerate(todo, 1):
            try:
                res = answer_question(
                    conn, item.question, embedder=embedder, reranker=reranker, llm=llm,
                    plan=make_plan(item.question), candidates=settings.rerank_candidates,
                    top_n=settings.rerank_top_n, min_rerank_score=settings.answer_min_rerank_score,
                )  # fmt: skip
            except LLMError as exc:
                print(f"{item.id}: LLM lỗi ({exc}); dừng – chạy lại để làm tiếp")
                break
            finally:
                reranker.save()
            _append(ANSWERS, {
                "id": item.id,
                "answer": res.answer,
                "refused": res.refused,
                "refusal_reason": res.refusal_reason,
                "warnings": res.warnings,
                "citations": [
                    {"label": c.label, "document": c.hit.document_number,
                     "article": c.hit.article, "clause": c.hit.clause}
                    for c in res.citations if c.hit
                ],
                # Ngữ cảnh đúng như LLM đã thấy (kèm tình trạng hiệu lực) – dùng cho Faithfulness
                "contexts": [
                    f"{h.citation} {h.document_title}. "
                    f"Hiệu lực: {describe_validity(h)}\n{h.content}"
                    for h in res.hits
                ],
                "model": res.model,
                "timings": res.timings,
            })  # fmt: skip
            print(f"[{n}/{len(todo)}] {item.id} {'TỪ CHỐI ' if res.refused else ''}"
                  f"{res.model} {sum(res.timings.values()):.1f}s", flush=True)  # fmt: skip
            if pause and not res.refused:
                time.sleep(pause)  # giãn cách để không vượt giới hạn request/phút của gói miễn phí


# ------------------------------------------------------------------------------- RAGAS


class _BgeEmbeddings:
    """Embedding bge-m3 của hệ thống cho Answer Relevancy (thay embedding của OpenAI)."""

    def __new__(cls):
        from ragas.embeddings.base import BaseRagasEmbedding

        from app.pipeline.embedding import get_embedder

        class Bge(BaseRagasEmbedding):
            def __init__(self) -> None:
                super().__init__()
                self.model = get_embedder()

            def embed_text(self, text: str, **kwargs) -> list[float]:
                return self.model.encode([text])[0].tolist()

            async def aembed_text(self, text: str, **kwargs) -> list[float]:
                return self.embed_text(text)

            def embed_texts(self, texts: list[str], **kwargs) -> list[list[float]]:
                return self.model.encode(texts).tolist()

            async def aembed_texts(self, texts: list[str], **kwargs) -> list[list[float]]:
                return self.embed_texts(texts)

        return Bge()


def _judge(model: str | None):
    from openai import AsyncOpenAI
    from ragas.cache import DiskCacheBackend
    from ragas.llms.base import llm_factory

    from app.core.config import get_settings

    s = get_settings()
    # Khóa thật do proxy của môi trường gắn vào; SDK OpenAI bắt buộc có giá trị nên dùng giá trị giả
    client = AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key or "proxy-injected",
                         max_retries=6)  # fmt: skip
    return llm_factory(model or s.llm_model, client=client, adapter="instructor",
                       cache=DiskCacheBackend(str(ROOT / ".cache" / "ragas")),
                       temperature=0.0, max_tokens=4096)  # fmt: skip


def strip_for_scoring(answer: str) -> str:
    """Bỏ cảnh báo hiệu lực do hệ thống tự gắn (⚠️, không do LLM viết) trước khi chấm."""
    return "\n".join(line for line in answer.splitlines() if not line.lstrip().startswith("⚠"))


async def _ragas(items: list[GoldenItem], limit: int | None, model: str | None, pause: float):
    from ragas.metrics.collections import AnswerRelevancy, Faithfulness

    answers, scored = _read(ANSWERS), _read(RAGAS)
    todo = [i for i in items if i.id in answers and i.id not in scored
            and not answers[i.id]["refused"]][:limit]  # fmt: skip
    print(f"Đã chấm {len(scored)} câu; chấm thêm {len(todo)}")
    llm = _judge(model)
    faithfulness = Faithfulness(llm=llm)
    relevancy = AnswerRelevancy(llm=llm, embeddings=_BgeEmbeddings(), strictness=3)
    for n, item in enumerate(todo, 1):
        a = answers[item.id]
        response = strip_for_scoring(a["answer"])
        f = r = None
        for attempt in range(3):
            try:
                f = await faithfulness.ascore(user_input=item.question, response=response,
                                              retrieved_contexts=a["contexts"])  # fmt: skip
                r = await relevancy.ascore(user_input=item.question, response=response)
                break
            except Exception as exc:  # noqa: BLE001 – quá tải (503) thì chờ; hết quota thì dừng
                print(f"{item.id}: giám khảo lỗi ({type(exc).__name__}: {str(exc)[:200]})")
                if "429" in str(exc) or attempt == 2:
                    break
                await asyncio.sleep(60 * (attempt + 1))
        if f is None or r is None:
            print("Dừng – chạy lại lệnh để chấm tiếp")
            break
        _append(RAGAS, {"id": item.id, "faithfulness": f.value, "answer_relevancy": r.value})
        print(f"[{n}/{len(todo)}] {item.id} faithfulness={f.value:.2f} relevancy={r.value:.2f}",
              flush=True)  # fmt: skip
        if pause:
            await asyncio.sleep(pause)


# ------------------------------------------------------------------------------- report


def evaluate(item: GoldenItem, a: dict) -> dict:
    out: dict = {"refusal_ok": a["refused"] == item.expect_refusal}
    if item.expect_refusal or a["refused"]:
        return out
    text = a["answer"]
    facts = [has_fact(text, f) for f in item.key_facts]
    out["facts_ok"] = all(facts)
    out["fact_rate"] = sum(facts) / len(facts) if facts else 1.0
    cites = a["citations"]

    def cited(r, c) -> bool:
        return matches(r, c["document"], c["article"], c["clause"])

    good = [c for c in cites if any(cited(r, c) for r in item.references)]
    out["citation_precision"] = len(good) / len(cites) if cites else 0.0
    out["citation_recall"] = sum(any(cited(r, c) for c in cites) for r in item.references) / len(
        item.references
    )
    out["forbidden_ok"] = not any(has_fact(text, f) for f in item.forbidden)
    return out


def report(items: list[GoldenItem]) -> dict:
    answers, scored = _read(ANSWERS), _read(RAGAS)
    rows = {i.id: evaluate(i, answers[i.id]) | {"type": i.type, "domain": i.domain}
            for i in items if i.id in answers}  # fmt: skip
    for i, r in rows.items():
        if i in scored:
            r |= {k: scored[i][k] for k in ("faithfulness", "answer_relevancy")}

    def mean(key: str, pick=lambda r: True) -> float | None:
        vals = [r[key] for r in rows.values() if key in r and r[key] is not None and pick(r)]
        return statistics.mean(vals) if vals else None

    by_id = {i.id: i for i in items}
    answerable = [r for k, r in rows.items() if not by_id[k].expect_refusal]
    refusal_items = [r for k, r in rows.items() if by_id[k].expect_refusal]
    summary = {
        "answers": len(rows),
        "accuracy_key_facts": mean("facts_ok"),
        "citation_precision": mean("citation_precision"),
        "citation_recall": mean("citation_recall"),
        "false_refusal": sum(not r["refusal_ok"] for r in answerable) / len(answerable)
        if answerable
        else None,
        "correct_refusal": sum(r["refusal_ok"] for r in refusal_items) / len(refusal_items)
        if refusal_items
        else None,
        "injection_resisted": mean("forbidden_ok", lambda r: r["type"] == "injection"),
        "faithfulness": mean("faithfulness"),
        "answer_relevancy": mean("answer_relevancy"),
        "ragas_scored": sum("faithfulness" in r for r in rows.values()),
    }
    by_type = defaultdict(list)
    for r in answerable:
        if "facts_ok" in r:
            by_type[r["type"]].append(r["facts_ok"])
    summary["accuracy_by_type"] = {t: statistics.mean(v) for t, v in sorted(by_type.items())}
    REPORT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cmd", choices=["generate", "ragas", "report"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep", type=float, default=4.0, help="giây nghỉ giữa các lượt gọi LLM")
    parser.add_argument("--judge-model", help="mô hình giám khảo RAGAS (mặc định LLM_MODEL)")
    parser.add_argument("--ids", nargs="*", help="chỉ chạy các câu này")
    parser.add_argument(
        "--run", default="", help="tên lượt chạy: lưu vào answers_<run>.jsonl (so sánh cấu hình)"
    )
    args = parser.parse_args()
    if args.run:
        global ANSWERS, RAGAS, REPORT
        ANSWERS = RESULTS / f"answers_{args.run}.jsonl"
        RAGAS = RESULTS / f"ragas_{args.run}.jsonl"
        REPORT = RESULTS / f"answers_report_{args.run}.json"
    items = load_golden()
    if args.ids:
        items = [i for i in items if i.id in set(args.ids)]
    if args.cmd == "generate":
        generate(items, args.limit, args.sleep)
    elif args.cmd == "ragas":
        asyncio.run(_ragas(items, args.limit, args.judge_model, args.sleep))
    print(json.dumps(report(load_golden()), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
