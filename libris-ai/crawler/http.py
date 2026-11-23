"""HTTP client lịch sự: giãn cách request theo host, retry có backoff, giới hạn dung lượng."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; legal-doc-crawler/0.1)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


class PoliteClient:
    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        retries: int = 4,
        timeout: float = 90.0,
        max_bytes: int = 50 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.min_interval = min_interval
        self.retries = retries
        self.max_bytes = max_bytes
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "vi,en;q=0.5"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        wait = self._last_request.get(host, 0.0) + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                backoff = min(2.0**attempt, 30.0)
                log.warning("Thử lại %s %s sau %.0fs (%s)", method, url, backoff, last_error)
                time.sleep(backoff)
            self._throttle(url)
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if resp.status_code in RETRY_STATUS:
                last_error = FetchError(f"HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise FetchError(f"{method} {url} -> HTTP {resp.status_code}")
            return resp
        raise FetchError(f"{method} {url} thất bại sau {self.retries + 1} lần: {last_error}")

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.request("GET", url, **kwargs).text

    def post_form(self, url: str, data: dict[str, str]) -> str:
        return self.request("POST", url, data=data).text

    def download(self, url: str) -> bytes:
        resp = self.request("GET", url)
        if len(resp.content) > self.max_bytes:
            raise FetchError(f"{url} vượt quá {self.max_bytes} bytes")
        return resp.content
