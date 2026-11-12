"""Cache abstraction compatible with in-memory dev storage and future Redis."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol


class CacheBackend(Protocol):
    """Abstract cache contract so Redis can replace InMemoryTTLCache without caller changes."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear(self) -> None: ...

    def stats(self) -> dict[str, int]: ...


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class InMemoryTTLCache:
    """Thread-safe LRU + TTL in-memory cache for Phase 2 Windows development."""

    def __init__(self, default_ttl_seconds: int = 900, max_entries: int = 1024) -> None:
        self._default_ttl = default_ttl_seconds
        self._max_entries = max_entries
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expires_at <= now:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return
        expires_at = time.monotonic() + ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = _CacheEntry(value=value, expires_at=expires_at)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "max_entries": self._max_entries,
            }
