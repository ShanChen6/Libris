from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.pipeline.embedding import get_embedder
from app.retrieval.rerank import get_reranker
from tests.fakes import FakeReranker
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)


def _client(conninfo: str, embedder) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=conninfo)
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_reranker] = FakeReranker
    return TestClient(app)


def test_search_endpoint(seeded) -> None:  # noqa: F811
    conninfo, emb = seeded
    try:
        client = _client(conninfo, emb)
        res = client.post(
            "/search",
            json={"query": "xe mô tô không có gương chiếu hậu bên trái bị phạt", "top_n": 3},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["plan"]["mode"] == "current"
        assert body["plan"]["statuses"] == ["ACTIVE", "AMENDED"]
        assert len(body["hits"]) <= 3
        top = body["hits"][0]
        assert top["document_number"] == "168/2024/NĐ-CP"
        assert top["citation"].endswith("- 168/2024/NĐ-CP]")
        assert {"vec_rank", "kw_rank", "char_start", "replaced_by"} <= top.keys()
        assert body["reranked"] is True and top["rerank_score"] is not None
        assert top["hybrid_rank"] >= 1

        plain = client.post(
            "/search", json={"query": "gương chiếu hậu", "rerank": False, "top_n": 2}
        ).json()
        assert plain["reranked"] is False and len(plain["hits"]) <= 2
        assert all(h["rerank_score"] is None for h in plain["hits"])

        old = client.post(
            "/search",
            json={"query": "gương chiếu hậu", "include_expired": True, "top_n": 10},
        ).json()
        assert "EXPIRED" in old["plan"]["statuses"]
        assert "100/2019/NĐ-CP" in {h["document_number"] for h in old["hits"]}

        past = client.post(
            "/search", json={"query": "gương chiếu hậu", "as_of": "2022-06-01", "rerank": False}
        ).json()
        assert past["plan"]["mode"] == "point_in_time"
        # Chỉ văn bản có hiệu lực ngày 01/6/2022 (NĐ 168/2024 có hiệu lực từ 2025)
        assert {h["document_number"] for h in past["hits"]} <= {"100/2019/NĐ-CP", "45/2013/QH13"}
        assert past["hits"][0]["document_number"] == "100/2019/NĐ-CP"

        assert client.post("/search", json={"query": ""}).status_code == 422
    finally:
        app.dependency_overrides.clear()
