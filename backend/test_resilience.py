"""Regression checks for cache, retry, timeout and circuit-breaker behavior."""

import time

from app.harness.resilience import CircuitOpenError, ResilientExecutor


def main() -> None:
    calls = 0
    executor = ResilientExecutor(
        cache_ttl_seconds=10,
        timeout_seconds=0.2,
        max_retries=1,
        retry_delay_seconds=0,
        circuit_failure_threshold=3,
        circuit_recovery_seconds=0.1,
    )

    def cached_call():
        nonlocal calls
        calls += 1
        return {"ok": True}

    assert executor.call("cached", cached_call) == {"ok": True}
    assert executor.call("cached", cached_call) == {"ok": True}
    assert calls == 1

    transient_attempts = 0

    def transient_failure():
        nonlocal transient_attempts
        transient_attempts += 1
        if transient_attempts == 1:
            raise RuntimeError("temporary")
        return "recovered"

    assert executor.call("transient", transient_failure, cache=False) == "recovered"
    assert transient_attempts == 2

    timeout_executor = ResilientExecutor(
        timeout_seconds=0.01,
        max_retries=0,
        circuit_failure_threshold=3,
    )
    try:
        timeout_executor.call("slow", lambda: time.sleep(0.05), cache=False)
    except TimeoutError:
        pass
    else:
        raise AssertionError("timeout was not enforced")

    circuit_executor = ResilientExecutor(
        timeout_seconds=0.1,
        max_retries=0,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=10,
    )
    for _ in range(2):
        try:
            circuit_executor.call("broken", lambda: (_ for _ in ()).throw(RuntimeError("down")), cache=False)
        except RuntimeError:
            pass
    try:
        circuit_executor.call("broken", lambda: "should not run", cache=False)
    except CircuitOpenError:
        pass
    else:
        raise AssertionError("circuit did not open")

    print("resilience checks passed")


if __name__ == "__main__":
    main()
