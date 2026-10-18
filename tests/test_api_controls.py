from edurage.api.middleware import RateLimiter


def test_rate_limiter_uses_injected_clock_without_sleep() -> None:
    now = [100.0]
    limiter = RateLimiter(2, clock=lambda: now[0])

    assert limiter.allow()
    assert limiter.allow()
    assert not limiter.allow()
    now[0] = 160.0
    assert limiter.allow()
