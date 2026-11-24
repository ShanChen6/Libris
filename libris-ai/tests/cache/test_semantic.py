import json

import numpy as np
from fastapi.testclient import TestClient

from app.cache.semantic import SemanticCache, get_cache, signature
from app.core.config import Settings, get_settings
from app.generation.llm import get_llm
from app.main import app
from app.pipeline.embedding import get_embedder
from app.retrieval.rerank import get_reranker
from tests.fakes import FakeEmbedder, FakeLLM, FakeReranker
from tests.generation.test_answer import _cite_first
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)


def test_signature_separates_answers_that_embeddings_confuse() -> None:
    # bge-m3: 0,957 – vượt ngưỡng cosine nhưng mức phạt khác hẳn
    assert signature("Xe máy vượt đèn đỏ bị phạt bao nhiêu?") != signature(
        "Ô tô vượt đèn đỏ bị phạt bao nhiêu?"
    )
    assert signature("Hợp đồng 6 tháng nghỉ việc báo trước mấy ngày?") != signature(
        "Hợp đồng 2 năm nghỉ việc báo trước mấy ngày?"
    )
    assert signature("Làm thêm ngày thường được trả bao nhiêu?") != signature(
        "Làm thêm ngày lễ được trả bao nhiêu?"
    )
    assert signature("Đất nông nghiệp có thời hạn bao lâu?") != signature(
        "Đất phi nông nghiệp có thời hạn bao lâu?"
    )
    assert signature("Mức phạt nồng độ cồn hiện nay?") != signature(
        "So sánh mức phạt nồng độ cồn cũ và mới"
    )
    # Diễn đạt lại cùng ý: cùng chữ ký
    assert signature("Không đội mũ bảo hiểm khi đi xe máy bị phạt bao nhiêu tiền?") == signature(
        "đi xe gắn máy mà không đội mũ bảo hiểm thì phạt bao nhiêu"
    )


def _unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=8).astype(np.float32)
    return v / np.linalg.norm(v)


def test_store_and_lookup(redis_client) -> None:
    client, prefix = redis_client
    cache = SemanticCache(client, threshold=0.95, ttl=60, prefix=prefix)
    q, v = "Xe máy vượt đèn đỏ bị phạt bao nhiêu?", _unit(1)
    scope = cache.scope(None, None, "2026-11-23", "v1")
    assert cache.lookup(q, v, scope) is None
    cache.store(q, v, scope, {"answer": "4.000.000 – 6.000.000 đồng"})

    near = v + 0.05 * _unit(2)
    near /= np.linalg.norm(near)
    hit = cache.lookup("xe máy vượt đèn đỏ bị phạt bao nhiêu", near, scope)
    assert hit and hit.payload["answer"].startswith("4.000.000") and hit.similarity > 0.95
    assert hit.question == q
    # Giống vector nhưng khác chữ ký (ô tô), khác scope (ngày / kho dữ liệu khác), hoặc khác xa
    assert cache.lookup("Ô tô vượt đèn đỏ bị phạt bao nhiêu?", v, scope) is None
    assert cache.lookup(q, v, cache.scope(None, None, "2026-11-24", "v1")) is None
    assert cache.lookup(q, _unit(3), scope) is None
    # Hết TTL: bị dọn khỏi vector set
    for key in client.scan_iter(f"{prefix}:entry:*"):
        client.delete(key)
    assert cache.lookup(q, v, scope) is None
    assert client.vset().vcard(f"{prefix}:vs:{scope}") == 0


def test_broken_redis_does_not_break_answers() -> None:
    class Down:
        def exists(self, *_):
            raise ConnectionError("redis down")

        def pipeline(self):
            raise ConnectionError("redis down")

    cache = SemanticCache(Down())
    assert cache.lookup("q", _unit(1), "s") is None
    cache.store("q", _unit(1), "s", {})  # không ném lỗi


def test_api_answers_from_cache(seeded, redis_client) -> None:  # noqa: F811
    conninfo, emb = seeded
    client, prefix = redis_client
    llm = FakeLLM(_cite_first)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=conninfo, rerank_candidates=10, rerank_top_n=3
    )
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_reranker] = FakeReranker
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_cache] = lambda: SemanticCache(client, prefix=prefix)
    try:
        api = TestClient(app)
        q = "xe mô tô không có gương chiếu hậu bên trái bị phạt bao nhiêu"
        first = api.post("/answer", json={"question": q}).json()
        assert first["cached"] is False and len(llm.calls) == 1
        again = api.post("/answer", json={"question": q.capitalize()}).json()
        assert again["cached"] is True and len(llm.calls) == 1  # không gọi LLM lần nữa
        assert again["answer"] == first["answer"] and again["question"] == q.capitalize()
        assert set(again["timings"]) == {"cache"}
        # Luồng SSE cũng trả từ cache, cùng thứ tự sự kiện
        body = api.post("/answer/stream", json={"question": q}).text
        events = [b.split("\n")[0].removeprefix("event: ") for b in body.strip().split("\n\n")]
        assert events == ["meta", "delta", "done"] and len(llm.calls) == 1
        done = json.loads(body.strip().split("\n\n")[-1].split("\n", 1)[1].removeprefix("data: "))
        assert done["cached"] is True
        # Tùy chọn khác (xem cả văn bản hết hiệu lực) -> scope khác -> không dùng cache
        # (LLM giả nêu mức tiền của văn bản mới cho đoạn văn bản cũ -> có thêm lượt viết lại)
        api.post("/answer", json={"question": q, "include_expired": True})
        assert len(llm.calls) > 1
    finally:
        app.dependency_overrides.clear()


def test_refusals_are_not_cached(seeded, redis_client) -> None:  # noqa: F811
    conninfo, emb = seeded
    client, prefix = redis_client
    cache = SemanticCache(client, prefix=prefix)
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=conninfo)
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_reranker] = FakeReranker
    app.dependency_overrides[get_llm] = lambda: FakeLLM("TỪ CHỐI\\nKhông có căn cứ.")
    app.dependency_overrides[get_cache] = lambda: cache
    try:
        body = TestClient(app).post("/answer", json={"question": "gương chiếu hậu xe mô tô"}).json()
        assert body["refused"] is True
        assert list(client.scan_iter(f"{prefix}:*")) == []
    finally:
        app.dependency_overrides.clear()


def test_vector_set_support_is_detected(redis_client) -> None:
    from app.cache.semantic import supports_vector_sets

    client, _ = redis_client
    assert supports_vector_sets(client)  # Redis 8

    class OldRedis:
        def execute_command(self, *args):
            raise Exception("ERR unknown command 'VCARD'")

    assert not supports_vector_sets(OldRedis())


def test_fake_embedder_dimension_is_used() -> None:
    assert FakeEmbedder().encode(["a"]).shape[1] == 1024
