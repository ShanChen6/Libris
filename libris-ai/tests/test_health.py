from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


def test_liveness() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "libris-ai"}


def test_readiness_reports_unreachable_services() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql://x:x@127.0.0.1:1/x",
        redis_url="redis://127.0.0.1:1/0",
    )
    try:
        res = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"]["postgres"]["status"] == "error"
    assert body["checks"]["redis"]["status"] == "error"
