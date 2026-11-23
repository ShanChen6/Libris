"""Đánh giá truy xuất trên Golden Dataset (Task 5.2) – không cần LLM.

    uv run python eval/eval_retrieval.py                       # mọi cấu hình
    uv run python eval/eval_retrieval.py --configs hybrid hybrid_rerank10

Chỉ số (Top K đoạn đưa cho LLM, mặc định K = 5), "đoạn đúng" = đoạn thuộc một căn cứ của câu hỏi
(cùng văn bản + Điều, và cùng Khoản nếu căn cứ ghi Khoản):

- Context Precision@K – công thức của RAGAS (dựa trên mã điều luật thay vì LLM chấm):
  Σ_k (Precision@k × v_k) / số đoạn đúng trong Top K. Đoạn đúng càng đứng đầu, điểm càng cao.
- Context Recall@K – tỷ lệ căn cứ của câu hỏi có mặt trong Top K.
- Hit@1, MRR – đoạn đúng đầu tiên đứng thứ mấy.
- Với câu ngoài phạm vi (phải từ chối): tỷ lệ bị chặn ngay ở ngưỡng rerank (không tốn lượt LLM);
  với câu trả lời được: tỷ lệ bị chặn nhầm.

Điểm rerank được lưu ở eval/.cache/rerank.json để so nhiều cấu hình mà không chấm lại.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psycopg

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from golden import GoldenItem, load_golden, matches  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.pipeline.embedding import get_embedder  # noqa: E402
from app.retrieval.hybrid import SearchWeights  # noqa: E402
from app.retrieval.service import make_plan, retrieve  # noqa: E402

CACHE = Path(os.environ.get("EVAL_RERANK_CACHE", ROOT / ".cache" / "rerank.json"))


@dataclass
class Config:
    weights: SearchWeights
    rerank: bool = False
    candidates: int = 20


CONFIGS = {
    "vector_only": Config(SearchWeights(vector=1, keyword=0)),
    "keyword_only": Config(SearchWeights(vector=0, keyword=1)),
    "hybrid": Config(SearchWeights()),
    "hybrid_kw0.5": Config(SearchWeights(vector=1, keyword=0.5)),
    "hybrid_kw2": Config(SearchWeights(vector=1, keyword=2)),
    "hybrid_kw0.25": Config(SearchWeights(vector=1, keyword=0.25)),
    "vector_rerank10": Config(SearchWeights(vector=1, keyword=0), rerank=True, candidates=10),
    "hybrid_kw0.25_rerank10": Config(
        SearchWeights(vector=1, keyword=0.25), rerank=True, candidates=10
    ),
    "hybrid_kw0.25_rerank20": Config(
        SearchWeights(vector=1, keyword=0.25), rerank=True, candidates=20
    ),
    "hybrid_rerank10": Config(SearchWeights(), rerank=True, candidates=10),
    "hybrid_rerank20": Config(SearchWeights(), rerank=True, candidates=20),
}


class CachingReranker:
    """Bọc reranker thật; điểm của cặp (câu hỏi, đoạn) đã chấm được lấy lại từ cache."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.cache: dict[str, float] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
        self.misses = 0

    @staticmethod
    def _key(query: str, passage: str) -> str:
        return hashlib.sha1(f"{query}\x00{passage}".encode()).hexdigest()

    def score(self, query: str, passages: list[str]) -> np.ndarray:
        keys = [self._key(query, p) for p in passages]
        todo = [i for i, k in enumerate(keys) if k not in self.cache]
        if todo:
            self.misses += len(todo)
            scores = self.inner.score(query, [passages[i] for i in todo])
            for i, s in zip(todo, scores, strict=True):
                self.cache[keys[i]] = float(s)
        return np.array([self.cache[k] for k in keys], dtype=np.float32)

    def save(self) -> None:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(self.cache))


def score_item(item: GoldenItem, hits) -> dict:
    rel = [any(matches(r, h.document_number, h.article, h.clause) for r in item.references)
           for h in hits]  # fmt: skip
    found = 0
    ap = 0.0
    for k, v in enumerate(rel, 1):
        if v:
            found += 1
            ap += found / k
    covered = sum(
        any(matches(r, h.document_number, h.article, h.clause) for h in hits)
        for r in item.references
    )
    first = next((k for k, v in enumerate(rel, 1) if v), None)
    return {
        "context_precision": ap / found if found else 0.0,
        "context_recall": covered / len(item.references),
        "hit1": 1.0 if first == 1 else 0.0,
        "mrr": 1 / first if first else 0.0,
    }


def run(config: Config, items, conn, embedder, reranker, k: int, min_score: float) -> dict:
    rows = []
    for item in items:
        started = time.perf_counter()
        res = retrieve(
            conn, item.question, embedder, reranker if config.rerank else None,
            candidates=config.candidates, top_n=k, plan=make_plan(item.question),
            weights=config.weights,
        )  # fmt: skip
        top = res.hits[0].rerank_score if res.hits and config.rerank else None
        row = {"id": item.id, "type": item.type, "domain": item.domain,
               "seconds": time.perf_counter() - started, "top_rerank": top,
               "hits": [f"{h.citation}" for h in res.hits]}  # fmt: skip
        if not item.expect_refusal:
            row.update(score_item(item, res.hits))
        if config.rerank:
            row["gated"] = top is None or top < min_score  # sẽ bị từ chối trước khi gọi LLM
        rows.append(row)
    answerable = [r for r in rows if "context_precision" in r]
    summary = {
        m: statistics.mean(r[m] for r in answerable)
        for m in ("context_precision", "context_recall", "hit1", "mrr")
    }
    summary["seconds"] = statistics.mean(r["seconds"] for r in rows)
    if config.rerank:
        out = [r for r in rows if "context_precision" not in r]
        summary["refusal_gate"] = sum(r["gated"] for r in out) / len(out) if out else None
        summary["false_gate"] = sum(r["gated"] for r in answerable) / len(answerable)
    by_type = defaultdict(list)
    for r in answerable:
        by_type[r["type"]].append(r["context_precision"])
    summary["precision_by_type"] = {t: statistics.mean(v) for t, v in sorted(by_type.items())}
    return {"summary": summary, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--configs", nargs="*", default=list(CONFIGS), choices=list(CONFIGS))
    parser.add_argument("-k", type=int, default=5, help="số đoạn đưa cho LLM")
    args = parser.parse_args()
    settings = get_settings()
    items = load_golden()
    embedder = get_embedder()
    reranker = None
    if any(CONFIGS[c].rerank for c in args.configs):
        from app.retrieval.rerank import get_reranker

        reranker = CachingReranker(get_reranker())
    results = {}
    with psycopg.connect(settings.database_url) as conn:
        for name in args.configs:
            started = time.perf_counter()
            results[name] = run(CONFIGS[name], items, conn, embedder, reranker, args.k,
                                settings.answer_min_rerank_score)  # fmt: skip
            if reranker:
                reranker.save()
            s = results[name]["summary"]
            print(f"{name:16} CP@{args.k} {s['context_precision']:.3f}  CR@{args.k} "
                  f"{s['context_recall']:.3f}  Hit@1 {s['hit1']:.3f}  MRR {s['mrr']:.3f}  "
                  f"{s['seconds']:.2f}s/câu  ({time.perf_counter() - started:.0f}s)",
                  flush=True)  # fmt: skip
    out = ROOT / "results" / "retrieval.json"
    previous = json.loads(out.read_text()) if out.exists() else {}
    out.write_text(json.dumps(previous | results, ensure_ascii=False, indent=1))
    print(f"\nChi tiết: {out}")


if __name__ == "__main__":
    main()
