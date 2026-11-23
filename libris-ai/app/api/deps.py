"""Phụ thuộc dùng chung cho các API nội bộ."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.core.config import Settings, get_settings


def require_internal_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    """libris-ai chỉ nhận request từ libris-api (cùng biết INTERNAL_API_TOKEN)."""
    expected = settings.internal_api_token
    if not expected:
        return  # chưa cấu hình: chế độ phát triển trên máy
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="Thiếu hoặc sai X-Internal-Token")


InternalAuth = Depends(require_internal_token)
