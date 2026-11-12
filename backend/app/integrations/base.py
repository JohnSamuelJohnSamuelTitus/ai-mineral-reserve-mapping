"""Shared HTTP adapter base with timeouts, exponential backoff, rate limiting, and caching."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from typing import Any

import httpx

from app.core.cache import CacheBackend, InMemoryTTLCache
from app.core.logging import get_logger

logger = get_logger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """Base error for external provider failures."""

    def __init__(self, provider_key: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"[{provider_key}] {message}")
        self.provider_key = provider_key
        self.status_code = status_code


class ProviderTimeoutError(ProviderError):
    """Raised when an external provider times out across all retries."""


class ProviderRateLimitError(ProviderError):
    """Raised when HTTP 429 persists after bounded retries."""


class ProviderUnavailableError(ProviderError):
    """Raised on HTTP 5xx (503/504) or connection failures after retries."""


class ProviderResponseError(ProviderError):
    """Raised when a provider returns malformed, unexpected, or error-flagged data."""


class AsyncRateLimiter:
    """Enforces a minimum interval between outbound requests per provider."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait_for = self._min_interval - (now - self._last_request_at)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request_at = time.monotonic()


class BaseProviderAdapter:
    """Reusable HTTP adapter with retries, exponential backoff, rate limiting, and caching."""

    provider_key: str = "base"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.4,
        requests_per_second: float = 5.0,
        cache: CacheBackend | None = None,
        cache_ttl_seconds: int = 900,
        user_agent: str = "AIMineralProspectivityAssistant/0.2",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self._rate_limiter = AsyncRateLimiter(requests_per_second)
        self._cache = cache or InMemoryTTLCache(default_ttl_seconds=cache_ttl_seconds)
        self._cache_ttl = cache_ttl_seconds
        self._user_agent = user_agent
        self._transport = transport

    def _cache_key(self, method: str, url: str, params: dict | None, json_body: dict | None) -> str:
        payload = json.dumps(
            {"m": method, "u": url, "p": params or {}, "b": json_body or {}},
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{self.provider_key}:{digest}"

    def _build_client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=min(5.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=self.timeout_seconds,
            pool=5.0,
        )
        return httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": self._user_agent},
            follow_redirects=True,
            transport=self._transport,
        )

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> httpx.Response:
        url = (
            path_or_url
            if path_or_url.startswith(("http://", "https://"))
            else f"{self.base_url}/{path_or_url.lstrip('/')}"
        )
        cache_key = self._cache_key(method.upper(), url, params, json_body)
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("%s cache hit for %s", self.provider_key, url)
                return cached

        last_exc: Exception | None = None
        async with self._build_client() as client:
            for attempt in range(self.max_retries + 1):
                await self._rate_limiter.acquire()
                try:
                    resp = await client.request(
                        method.upper(),
                        url,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
                except httpx.TimeoutException as exc:
                    last_exc = exc
                    logger.warning(
                        "%s timeout on %s (attempt %d/%d)",
                        self.provider_key,
                        url,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    if attempt < self.max_retries:
                        await self._sleep_backoff(attempt)
                        continue
                    raise ProviderTimeoutError(
                        self.provider_key, f"Request timed out after {self.max_retries + 1} attempts"
                    ) from exc
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning(
                        "%s transport error on %s: %s (attempt %d/%d)",
                        self.provider_key,
                        url,
                        exc,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    if attempt < self.max_retries:
                        await self._sleep_backoff(attempt)
                        continue
                    raise ProviderUnavailableError(
                        self.provider_key, f"Transport error: {exc}"
                    ) from exc

                if resp.status_code in RETRYABLE_STATUS_CODES:
                    logger.warning(
                        "%s returned HTTP %d on %s (attempt %d/%d)",
                        self.provider_key,
                        resp.status_code,
                        url,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    if attempt < self.max_retries:
                        retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                        await self._sleep_backoff(attempt, override=retry_after)
                        continue
                    if resp.status_code == 429:
                        raise ProviderRateLimitError(
                            self.provider_key,
                            "Rate limited (HTTP 429) after retries",
                            status_code=429,
                        )
                    raise ProviderUnavailableError(
                        self.provider_key,
                        f"Upstream unavailable (HTTP {resp.status_code})",
                        status_code=resp.status_code,
                    )

                if resp.status_code >= 400:
                    raise ProviderResponseError(
                        self.provider_key,
                        f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}",
                        status_code=resp.status_code,
                    )

                if use_cache:
                    self._cache.set(cache_key, resp, ttl_seconds=self._cache_ttl)
                return resp

        raise ProviderUnavailableError(self.provider_key, f"Request failed: {last_exc}")

    @staticmethod
    def _parse_retry_after(header_val: str | None) -> float | None:
        if not header_val:
            return None
        try:
            seconds = float(header_val.strip())
            return max(0.0, min(seconds, 5.0))
        except ValueError:
            return None

    async def _sleep_backoff(self, attempt: int, *, override: float | None = None) -> None:
        if override is not None:
            await asyncio.sleep(override)
            return
        delay = self.backoff_base_seconds * (2**attempt) + random.uniform(0.0, 0.1 * self.backoff_base_seconds)
        await asyncio.sleep(delay)
