from typing import Annotated

import psycopg
import redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/health", tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("")
def liveness(settings: SettingsDep) -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


def _check_postgres(url: str) -> dict[str, str]:
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
        if row is None:
            return {"status": "error", "detail": "extension 'vector' chưa được cài"}
        return {"status": "ok", "pgvector": row[0]}
    except psycopg.Error as exc:
        return {"status": "error", "detail": str(exc).strip()}


def _check_redis(url: str) -> dict[str, str]:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=3)
        client.ping()
        return {"status": "ok"}
    except redis.RedisError as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/ready")
def readiness(settings: SettingsDep) -> JSONResponse:
    checks = {
        "postgres": _check_postgres(settings.database_url),
        "redis": _check_redis(settings.redis_url),
    }
    ready = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "degraded", "checks": checks},
    )
