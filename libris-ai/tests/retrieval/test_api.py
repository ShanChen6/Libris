from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.pipeline.embedding import get_embedder
from tests.retrieval.test_hybrid import seeded  # noqa: F401  (fixture)


def _client(conninfo: str, embedder) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=conninfo)
    app.dependency_overrides[get_embedder] = lambda: embedder
    return TestClient(app)


def test_search_endpoint(seeded) -> None:  # noqa: F811
    conninfo, emb = seeded
    try:
        client = _client(conninfo, emb)
        res = client.post(
            "/search",
            json={"query": "xe mô tô không có gương chiếu hậu bên trái bị phạt", "top_k": 3},
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

        old = client.post(
            "/search",
            json={"query": "gương chiếu hậu", "include_expired": True, "top_k": 10},
        ).json()
        assert "EXPIRED" in old["plan"]["statuses"]
        assert "100/2019/NĐ-CP" in {h["document_number"] for h in old["hits"]}

        past = client.post(
            "/search", json={"query": "gương chiếu hậu", "as_of": "2022-06-01"}
        ).json()
        assert past["plan"]["mode"] == "point_in_time"
        # Chỉ văn bản có hiệu lực ngày 01/6/2022 (NĐ 168/2024 có hiệu lực từ 2025)
        assert {h["document_number"] for h in past["hits"]} <= {"100/2019/NĐ-CP", "45/2013/QH13"}
        assert past["hits"][0]["document_number"] == "100/2019/NĐ-CP"

        assert client.post("/search", json={"query": ""}).status_code == 422
    finally:
        app.dependency_overrides.clear()
