"""Tests for :mod:`ratelimit`."""

from __future__ import annotations

import math

import pytest

from ratelimit import KeyedLimiter, TokenBucket


class FakeClock:
    """A deterministic, manually advanced clock."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


def test_bucket_starts_full(clock):
    bucket = TokenBucket(5, 1.0, clock)
    assert bucket.allow(5) is True
    assert bucket.allow(1) is False


def test_allow_default_cost_is_one(clock):
    bucket = TokenBucket(2, 1.0, clock)
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_failed_allow_consumes_nothing(clock):
    bucket = TokenBucket(5, 1.0, clock)
    assert bucket.allow(3) is True
    assert bucket.allow(3) is False
    # The two remaining tokens are still available.
    assert bucket.allow(2) is True
    assert bucket.allow(1) is False


def test_refill_is_continuous(clock):
    bucket = TokenBucket(5, 1.0, clock)
    assert bucket.allow(5) is True
    clock.advance(2.5)
    assert bucket.allow(2) is True
    # 0.5 tokens left over; not enough for another.
    assert bucket.allow(1) is False


def test_refill_accumulates_across_calls(clock):
    bucket = TokenBucket(10, 2.0, clock)
    assert bucket.allow(10) is True
    clock.advance(1.0)
    assert bucket.allow(2) is True
    clock.advance(0.25)
    assert bucket.allow(0.5) is True


def test_refill_never_exceeds_capacity(clock):
    bucket = TokenBucket(3, 10.0, clock)
    assert bucket.allow(3) is True
    clock.advance(10_000)
    assert bucket.allow(3) is True
    assert bucket.allow(1) is False


def test_time_does_not_refill_by_itself(clock):
    bucket = TokenBucket(3, 1.0, clock)
    assert bucket.allow(3) is True
    clock.advance(0)
    assert bucket.allow(1) is False


def test_wait_time_zero_when_available(clock):
    bucket = TokenBucket(5, 1.0, clock)
    assert bucket.wait_time(5) == 0.0
    assert bucket.wait_time(1) == 0.0


def test_wait_time_matches_refill_rate(clock):
    bucket = TokenBucket(1, 0.5, clock)
    assert bucket.allow(1) is True
    assert bucket.wait_time(1) == pytest.approx(2.0)
    clock.advance(0.5)
    assert bucket.wait_time(1) == pytest.approx(1.5)


def test_wait_time_for_partial_deficit(clock):
    bucket = TokenBucket(10, 4.0, clock)
    assert bucket.allow(6) is True  # 4 tokens left
    assert bucket.wait_time(6) == pytest.approx(0.5)
    clock.advance(0.25)
    assert bucket.wait_time(6) == pytest.approx(0.25)


def test_wait_time_does_not_consume(clock):
    bucket = TokenBucket(1, 1.0, clock)
    assert bucket.allow(1) is True
    assert bucket.wait_time(1) == pytest.approx(1.0)
    assert bucket.wait_time(1) == pytest.approx(1.0)
    clock.advance(1.0)
    assert bucket.wait_time(1) == 0.0
    assert bucket.allow(1) is True


def test_wait_time_is_capped_by_capacity_but_not_overshooting(clock):
    bucket = TokenBucket(2, 1.0, clock)
    assert bucket.allow(2) is True
    clock.advance(100)
    assert bucket.wait_time(2) == 0.0
    assert bucket.allow(2) is True


def test_zero_refill_rate_never_recovers(clock):
    bucket = TokenBucket(2, 0.0, clock)
    assert bucket.allow(2) is True
    clock.advance(1000)
    assert bucket.allow(1) is False
    assert math.isinf(bucket.wait_time(1))
    assert bucket.wait_time(2) == math.inf


@pytest.mark.parametrize("cost", [0, -1, -100])
def test_allow_rejects_non_positive_cost(clock, cost):
    bucket = TokenBucket(5, 1.0, clock)
    with pytest.raises(ValueError):
        bucket.allow(cost)


def test_allow_rejects_cost_above_capacity(clock):
    bucket = TokenBucket(5, 1.0, clock)
    with pytest.raises(ValueError):
        bucket.allow(6)


def test_invalid_cost_does_not_consume(clock):
    bucket = TokenBucket(5, 1.0, clock)
    with pytest.raises(ValueError):
        bucket.allow(6)
    assert bucket.allow(5) is True


@pytest.mark.parametrize("cost", [0, -1, 6])
def test_wait_time_rejects_invalid_cost(clock, cost):
    bucket = TokenBucket(5, 1.0, clock)
    with pytest.raises(ValueError):
        bucket.wait_time(cost)


def test_cost_equal_to_capacity_is_allowed(clock):
    bucket = TokenBucket(4, 1.0, clock)
    assert bucket.wait_time(4) == 0.0
    assert bucket.allow(4) is True


def test_default_clock_uses_real_time():
    bucket = TokenBucket(1, 1000.0)
    assert bucket.allow(1) is True
    assert bucket.wait_time(1) <= 0.001


# ---------------------------------------------------------------------------
# KeyedLimiter
# ---------------------------------------------------------------------------


def test_keyed_limiter_starts_empty(clock):
    limiter = KeyedLimiter(5, 1.0, clock)
    assert len(limiter) == 0


def test_keyed_limiter_tracks_keys(clock):
    limiter = KeyedLimiter(5, 1.0, clock)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert len(limiter) == 2
    assert limiter.allow("a") is True
    assert len(limiter) == 2


def test_keyed_limiter_buckets_are_independent(clock):
    limiter = KeyedLimiter(2, 1.0, clock)
    assert limiter.allow("a", 2) is True
    assert limiter.allow("a", 1) is False
    # Another key has its own full bucket.
    assert limiter.allow("b", 2) is True
    assert limiter.allow("b", 1) is False


def test_keyed_limiter_refills_per_key(clock):
    limiter = KeyedLimiter(2, 1.0, clock)
    assert limiter.allow("a", 2) is True
    assert limiter.allow("b", 2) is True
    clock.advance(1.0)
    assert limiter.allow("a", 1) is True
    assert limiter.allow("b", 1) is True
    assert limiter.allow("a", 1) is False
    assert limiter.allow("b", 1) is False


def test_keyed_limiter_validates_cost(clock):
    limiter = KeyedLimiter(5, 1.0, clock)
    with pytest.raises(ValueError):
        limiter.allow("a", 0)
    with pytest.raises(ValueError):
        limiter.allow("a", 6)
    # An invalid call must not create or evict any key.
    assert len(limiter) == 0


def test_keyed_limiter_respects_max_keys(clock):
    limiter = KeyedLimiter(5, 1.0, clock, max_keys=2)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert len(limiter) == 2
    assert limiter.allow("c") is True
    assert len(limiter) == 2


def test_keyed_limiter_evicts_least_recently_used(clock):
    limiter = KeyedLimiter(5, 1.0, clock, max_keys=2)
    limiter.allow("a")
    limiter.allow("b")
    # Touch "a" so "b" becomes the least recently used key.
    limiter.allow("a")
    limiter.allow("c")
    assert len(limiter) == 2
    assert "a" in limiter
    assert "c" in limiter
    assert "b" not in limiter


def test_keyed_limiter_evicted_key_starts_fresh(clock):
    limiter = KeyedLimiter(2, 1.0, clock, max_keys=1)
    assert limiter.allow("a", 2) is True
    assert limiter.allow("a", 1) is False
    assert limiter.allow("b", 2) is True  # evicts "a"
    assert len(limiter) == 1
    # Re-adding "a" creates a new, full bucket rather than restoring state.
    assert limiter.allow("a", 2) is True
    assert "b" not in limiter


def test_keyed_limiter_eviction_order_is_lru(clock):
    limiter = KeyedLimiter(5, 1.0, clock, max_keys=3)
    for key in ("a", "b", "c"):
        limiter.allow(key)
    # Recency order is now c, b, a (a is least recent).
    limiter.allow("a")  # order: a, c, b
    limiter.allow("d")  # evicts b
    assert "b" not in limiter
    assert set(k for k in ("a", "c", "d") if k in limiter) == {"a", "c", "d"}
    limiter.allow("e")  # evicts c (a and d were more recent)
    assert "c" not in limiter
    assert "a" in limiter
    assert "d" in limiter
    assert "e" in limiter


def test_keyed_limiter_does_not_evict_at_limit_without_new_key(clock):
    limiter = KeyedLimiter(5, 1.0, clock, max_keys=2)
    limiter.allow("a")
    limiter.allow("b")
    for _ in range(10):
        limiter.allow("a")
        limiter.allow("b")
    assert len(limiter) == 2
    assert "a" in limiter and "b" in limiter


def test_keyed_limiter_default_max_keys(clock):
    limiter = KeyedLimiter(5, 1.0, clock)
    for i in range(1001):
        limiter.allow(i)
    assert len(limiter) == 1000
    assert 0 not in limiter
    assert 1000 in limiter


def test_keyed_limiter_max_keys_zero_tracks_nothing(clock):
    limiter = KeyedLimiter(5, 1.0, clock, max_keys=0)
    assert limiter.allow("a") is True
    assert len(limiter) == 0


def test_keyed_limiter_accepts_various_hashable_keys(clock):
    limiter = KeyedLimiter(5, 1.0, clock)
    assert limiter.allow(1) is True
    assert limiter.allow(("user", 2)) is True
    assert limiter.allow(None) is True
    assert len(limiter) == 3


def test_keyed_limiter_wait_time(clock):
    limiter = KeyedLimiter(2, 1.0, clock)
    assert limiter.allow("a", 2) is True
    assert limiter.wait_time("a", 1) == pytest.approx(1.0)
    assert limiter.wait_time("b", 1) == 0.0


# ---------------------------------------------------------------------------
# Floating point behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rate", [0.1, 0.3, 1 / 3, 7.0, 0.7, 1.5])
def test_waiting_exactly_wait_time_allows_request(rate):
    clock = FakeClock()
    capacity = 10
    bucket = TokenBucket(capacity, rate, clock)
    assert bucket.allow(capacity) is True
    assert bucket.allow(1) is False
    clock.advance(bucket.wait_time(1))
    assert bucket.allow(1) is True


def test_tokens_property_reflects_refill(clock):
    bucket = TokenBucket(10, 2.0, clock)
    assert bucket.tokens == 10.0
    assert bucket.allow(10) is True
    assert bucket.tokens == 0.0
    clock.advance(1.5)
    assert bucket.tokens == pytest.approx(3.0)
    assert bucket.allow(3) is True


def test_module_docstring_example():
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_rate=1.0, clock=clock)
    assert bucket.allow(2) is True
    assert bucket.allow() is False
    assert bucket.wait_time(1) == pytest.approx(1.0)
