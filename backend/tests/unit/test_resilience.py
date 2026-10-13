import time

import pytest

from app.harness.resilience import CircuitOpenError, ResilientExecutor


def test_cache_prevents_duplicate_operation():
    calls = 0
    executor = ResilientExecutor(cache_ttl_seconds=10, timeout_seconds=0.2, max_retries=1, retry_delay_seconds=0)

    def operation():
        nonlocal calls
        calls += 1
        return {"ok": True}

    assert executor.call("cached", operation) == {"ok": True}
    assert executor.call("cached", operation) == {"ok": True}
    assert calls == 1


def test_transient_failure_is_retried():
    attempts = 0
    executor = ResilientExecutor(timeout_seconds=0.2, max_retries=1, retry_delay_seconds=0)

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")
        return "recovered"

    assert executor.call("transient", operation, cache=False) == "recovered"
    assert attempts == 2


def test_timeout_is_enforced():
    executor = ResilientExecutor(timeout_seconds=0.01, max_retries=0)
    with pytest.raises(TimeoutError):
        executor.call("slow", lambda: time.sleep(0.05), cache=False)


def test_circuit_breaker_opens_after_failures():
    executor = ResilientExecutor(timeout_seconds=0.1, max_retries=0, circuit_failure_threshold=2, circuit_recovery_seconds=10)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            executor.call("broken", lambda: (_ for _ in ()).throw(RuntimeError("down")), cache=False)
    with pytest.raises(CircuitOpenError):
        executor.call("broken", lambda: "should not run", cache=False)
