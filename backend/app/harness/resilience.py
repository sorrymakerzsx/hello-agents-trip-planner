"""Small synchronous resilience primitives for external tool calls."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable


class CircuitOpenError(RuntimeError):
    """Raised while an external dependency is temporarily considered unhealthy."""


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, max_size: int = 256) -> None:
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._items: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[bool, Any]:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return False, None
            if item.expires_at <= now:
                del self._items[key]
                return False, None
            self._items.move_to_end(key)
            return True, item.value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._items[key] = _CacheEntry(value, time.monotonic() + ttl_seconds)
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 30.0) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if recovery_seconds <= 0:
            raise ValueError("recovery_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at < self.recovery_seconds:
                raise CircuitOpenError("external service circuit is open")
            if self._half_open_probe:
                raise CircuitOpenError("external service recovery probe is in progress")
            self._half_open_probe = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._half_open_probe = False
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if time.monotonic() - self._opened_at >= self.recovery_seconds:
                return "half_open"
            return "open"


class ResilientExecutor:
    """Add cache, timeout, retry and circuit-breaker behavior to sync calls."""

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = 300.0,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.5,
        circuit_failure_threshold: int = 3,
        circuit_recovery_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0 or max_retries < 0 or retry_delay_seconds < 0:
            raise ValueError("invalid resilience settings")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.cache = TTLCache()
        self.breaker = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_seconds=circuit_recovery_seconds,
        )
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="resilience")

    def call(
        self,
        key: str,
        operation: Callable[[], Any],
        *,
        cache: bool = True,
    ) -> Any:
        if cache:
            hit, value = self.cache.get(key)
            if hit:
                return value

        self.breaker.before_call()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            future = self._executor.submit(operation)
            try:
                value = future.result(timeout=self.timeout_seconds)
                self.breaker.record_success()
                if cache:
                    self.cache.set(key, value, self.cache_ttl_seconds)
                return value
            except FutureTimeoutError as exc:
                future.cancel()
                last_error = TimeoutError(
                    f"external call timed out after {self.timeout_seconds}s"
                )
                last_error.__cause__ = exc
            except Exception as exc:  # noqa: PERF203 - retry boundary
                last_error = exc

            if attempt < self.max_retries:
                time.sleep(self.retry_delay_seconds * (2**attempt))

        self.breaker.record_failure()
        assert last_error is not None
        raise last_error

    def stats(self) -> dict[str, Any]:
        return {
            "circuit_state": self.breaker.state,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "cache_ttl_seconds": self.cache_ttl_seconds,
        }
