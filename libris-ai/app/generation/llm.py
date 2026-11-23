"""Client LLM theo chuẩn OpenAI Chat Completions (Gemini, OpenAI, Qwen/DashScope... đều hỗ trợ)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
FALLBACK_STATUS = RETRY_STATUS | {404}  # 404: mô hình không còn phục vụ -> thử mô hình khác


class LLMError(RuntimeError):
    pass


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class Completion:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency: float = 0.0


class LLMClient(Protocol):
    def complete(self, messages: list[Message]) -> Completion: ...

    def stream(self, messages: list[Message]) -> Iterator[str]:
        """Từng mẩu văn bản theo thời gian thực (dùng cho SSE, Task 4.2)."""
        ...


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        models: list[str],
        api_key: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        reasoning_effort: str | None = None,
        timeout: float = 60.0,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not models:
            raise ValueError("cần ít nhất một mô hình")
        self.models = models
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.retries = retries
        self.last_model: str | None = None  # mô hình phục vụ lần gọi gần nhất
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def _payload(self, model: str, messages: list[Message], stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def _attempts(self) -> Iterator[str]:
        """Mỗi vòng thử lần lượt mọi mô hình (mô hình chính quá tải -> chuyển ngay sang dự phòng);
        hết vòng mới chờ rồi thử lại."""
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(min(2.0 * attempt, 8.0))
            yield from self.models

    @staticmethod
    def _error(resp: httpx.Response) -> str:
        try:
            body = resp.json()
            if isinstance(body, list):
                body = body[0]
            return str(body.get("error", {}).get("message", resp.text))[:300]
        except (ValueError, AttributeError, IndexError):
            return resp.text[:300]

    @staticmethod
    def _should_retry(status: int) -> bool:
        """True: thử mô hình kế tiếp / vòng sau; False: lỗi không phục hồi được (VD 400, 401)."""
        return status in FALLBACK_STATUS

    def complete(self, messages: list[Message]) -> Completion:
        last = ""
        skip: set[str] = set()
        for model in self._attempts():
            if model in skip:
                continue  # 404: mô hình không còn phục vụ, không thử lại ở vòng sau
            started = time.monotonic()
            try:
                resp = self._http.post(
                    "chat/completions", json=self._payload(model, messages, False)
                )
            except httpx.TransportError as exc:
                last = f"{model}: {exc}"
                continue
            if resp.status_code == 200:
                data = resp.json()
                self.last_model = data.get("model", model)
                text = data["choices"][0]["message"].get("content") or ""
                return Completion(
                    text=text,
                    model=data.get("model", model),
                    usage=data.get("usage") or {},
                    latency=time.monotonic() - started,
                )
            last = f"{model}: HTTP {resp.status_code} {self._error(resp)}"
            log.warning("LLM lỗi: %s", last)
            if not self._should_retry(resp.status_code):
                raise LLMError(last)
            if resp.status_code == 404:
                skip.add(model)
        raise LLMError(f"Không gọi được LLM sau khi thử {self.models}: {last}")

    def stream(self, messages: list[Message]) -> Iterator[str]:
        last = ""
        for model in self._attempts():
            try:
                with self._http.stream(
                    "POST", "chat/completions", json=self._payload(model, messages, True)
                ) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        last = f"{model}: HTTP {resp.status_code} {self._error(resp)}"
                        if not self._should_retry(resp.status_code):
                            raise LLMError(last)
                        continue
                    self.last_model = model
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        chunk = json.loads(data)
                        for choice in chunk.get("choices", []):
                            delta = (choice.get("delta") or {}).get("content")
                            if delta:
                                yield delta
                    return
            except httpx.TransportError as exc:
                last = f"{model}: {exc}"
        raise LLMError(f"Không gọi được LLM sau khi thử {self.models}: {last}")


@lru_cache
def get_llm() -> OpenAICompatibleClient:
    s = get_settings()
    return OpenAICompatibleClient(
        base_url=s.llm_base_url,
        models=[s.llm_model, *[m for m in s.llm_fallback_models if m != s.llm_model]],
        api_key=s.llm_api_key,
        temperature=s.llm_temperature,
        max_tokens=s.llm_max_tokens,
        reasoning_effort=s.llm_reasoning_effort,
        timeout=s.llm_timeout,
        retries=s.llm_retries,
    )
