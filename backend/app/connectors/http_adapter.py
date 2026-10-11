"""Fixed-route HTTP calls. Redirects are refused and credentials stay on the original origin.

Only GET is retried. Write methods must be requested explicitly and are never retried.
"""

import asyncio
import random
import time
from contextvars import ContextVar
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import Settings
from app.connectors.pinned_transport import pinned_transport
from app.connectors.ssrf_guard import validate_destination
from app.errors import HubError
from app.security.budgets import concurrency_slot

_transport_override: ContextVar[httpx.AsyncBaseTransport | None] = ContextVar(
    "hub_http_transport", default=None
)
_last_retries: ContextVar[int] = ContextVar("hub_last_retries", default=0)


def last_retry_count() -> int:
    return _last_retries.get()


def push_transport(transport: httpx.AsyncBaseTransport | None):
    return _transport_override.set(transport)


def reset_transport(token) -> None:
    _transport_override.reset(token)


def _classify(exc: Exception) -> HubError:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return HubError("UPSTREAM_TIMEOUT", "The connected application timed out", 504)
    if isinstance(exc, httpx.TransportError):
        return HubError("UPSTREAM_UNAVAILABLE", "The connected application could not be reached", 502)
    return HubError("UPSTREAM_ERROR", "The connected application returned an error", 502)


async def execute_request(*, url: str, settings: Settings, **kwargs) -> tuple[int, bytes, int]:
    _last_retries.set(0)
    parsed = urlsplit(url)
    with concurrency_slot(f"connector:{parsed.hostname}:{parsed.port or (443 if parsed.scheme == "https" else 80)}", settings.connector_concurrency):
        return await _execute_request(url=url, settings=settings, **kwargs)


async def _execute_request(
    *,
    method: str,
    url: str,
    settings: Settings,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json_body: dict | None = None,
    timeout_ms: int = 5000,
    max_bytes: int = 1_048_576,
    retries: int = 2,
    tls_verify: bool = True,
    write: bool = False,
) -> tuple[int, bytes, int]:
    _last_retries.set(0)
    allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"} if write else {"GET", "POST"}
    if method not in allowed:
        raise HubError("VALIDATION_FAILED", "This HTTP method is not allowed for the request", 422)
    timeout = httpx.Timeout(timeout_ms / 1000)
    verify: bool | str = tls_verify
    if not tls_verify and not settings.allow_insecure_tls:
        raise HubError("UNSAFE_CONFIGURATION", "TLS verification cannot be disabled", 422)
    started = time.perf_counter()
    attempt = 0
    last_error: HubError | None = None
    while True:
        attempt += 1
        remaining = timeout_ms / 1000 - (time.perf_counter() - started)
        if remaining <= 0:
            raise HubError("UPSTREAM_TIMEOUT", "The connected application timed out", 504)
        # Resolve again immediately before the attempt so a rebinding answer is re-checked.
        try:
            async with asyncio.timeout(remaining):
                host, port, addresses = await asyncio.to_thread(validate_destination, url, settings)
        except TimeoutError as exc:
            raise HubError("UPSTREAM_TIMEOUT", "The connected application timed out", 504) from exc
        transport = _transport_override.get()
        client_kwargs: dict = {"timeout": timeout, "verify": verify, "follow_redirects": False, "trust_env": False,
                               "transport": transport or pinned_transport(host, port, addresses, tls_verify)}
        try:
            async with asyncio.timeout(max(0.001, timeout_ms / 1000 - (time.perf_counter() - started))):
                async with httpx.AsyncClient(**client_kwargs) as client:
                    async with client.stream(method, url, headers=headers, params=params, json=json_body) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            raise HubError("SSRF_BLOCKED", "Redirects are not allowed for connector calls", 422)
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if response.is_success and content_type != "application/json" and not content_type.endswith("+json"):
                            raise HubError("SCHEMA_MISMATCH", "Upstream response must use a JSON content type", 502)
                        parts = []
                        size = 0
                        async for chunk in response.aiter_bytes(chunk_size=16384):
                            size += len(chunk)
                            if size > max_bytes:
                                raise HubError("PAYLOAD_TOO_LARGE", "Upstream payload exceeds the limit", 413)
                            parts.append(chunk)
                        body = b"".join(parts)
        except HubError:
            raise
        except Exception as exc:
            last_error = _classify(exc)
            retryable = method == "GET" and last_error.code in {"UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE"}
            if retryable and attempt <= retries:
                _last_retries.set(attempt)
                await _sleep(0.05 * (2 ** (attempt - 1)) + random.random() * 0.01)
                continue
            raise last_error from exc
        elapsed = int((time.perf_counter() - started) * 1000)
        if method == "GET" and response.status_code in {502, 503, 504} and attempt <= retries:
            _last_retries.set(attempt)
            await _sleep(0.05 * (2 ** (attempt - 1)))
            continue
        return response.status_code, body, elapsed


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def join_url(base_url: str, path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise HubError("VALIDATION_FAILED", "Connector path must be a rooted relative path", 422)
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))

