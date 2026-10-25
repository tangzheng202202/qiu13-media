import math

import pytest

from ratelimit import KeyedLimiter, TokenBucket


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_bucket_starts_full_and_failed_allow_consumes_nothing():
    clock = FakeClock()
    bucket = TokenBucket(3, 1.0, clock=clock)

    assert bucket.allow(cost=2)
    assert not bucket.allow(cost=2)

    # The failed request left the remaining token available.  Together with
    # the continuous refill, there are two tokens after one second.
    clock.advance(1.0)
    assert bucket.allow(cost=2)
    assert not bucket.allow()


def test_refill_is_continuous_and_capped_at_capacity():
    clock = FakeClock()
    bucket = TokenBucket(2, 2.0, clock=clock)

    assert bucket.allow(cost=2)
    clock.advance(0.25)
    assert not bucket.allow()
    clock.advance(0.25)
    assert bucket.allow()

    clock.advance(100.0)
    assert bucket.allow(cost=2)
    assert not bucket.allow()


@pytest.mark.parametrize("method_name", ["allow", "wait_time"])
@pytest.mark.parametrize("cost", [0, -1, 4])
def test_invalid_costs_raise_value_error(method_name, cost):
    bucket = TokenBucket(3, 1.0, clock=FakeClock())
    method = getattr(bucket, method_name)

    with pytest.raises(ValueError):
        method(cost=cost)


def test_wait_time_reports_time_needed_without_consuming_tokens():
    clock = FakeClock()
    bucket = TokenBucket(4, 2.0, clock=clock)
    assert bucket.allow(cost=4)

    clock.advance(0.5)  # One token has refilled.
    assert bucket.wait_time(cost=3) == pytest.approx(1.0)
    assert bucket.wait_time(cost=1) == 0.0
    # Neither query consumed the token that is already available.
    assert bucket.wait_time(cost=3) == pytest.approx(1.0)

    clock.advance(1.0)
    assert bucket.wait_time(cost=3) == 0.0
    assert bucket.allow(cost=3)


def test_wait_time_with_no_refill_is_infinite_when_tokens_are_insufficient():
    bucket = TokenBucket(1, 0.0, clock=FakeClock())
    assert bucket.allow()
    assert math.isinf(bucket.wait_time())


def test_keyed_limiter_uses_independent_buckets():
    clock = FakeClock()
    limiter = KeyedLimiter(2, 1.0, clock=clock)

    assert limiter.allow("alice", cost=2)
    assert not limiter.allow("alice")
    assert limiter.allow("bob", cost=2)
    assert len(limiter) == 2

    clock.advance(1.0)
    assert limiter.allow("alice")
    assert not limiter.allow("alice")
    # Alice's requests have not consumed Bob's independently refilled token.
    assert limiter.allow("bob")


def test_keyed_limiter_evicts_least_recently_used_key():
    clock = FakeClock()
    limiter = KeyedLimiter(2, 0.0, clock=clock, max_keys=2)

    assert limiter.allow("a", cost=2)
    assert limiter.allow("b", cost=2)
    # Even an unsuccessful valid request is a use, making "b" the oldest key.
    assert not limiter.allow("a")
    assert limiter.allow("c")
    assert len(limiter) == 2

    # "a" was retained and is still empty; "b" was evicted, so its new bucket
    # starts full.
    assert not limiter.allow("a")
    assert limiter.allow("b", cost=2)
    assert len(limiter) == 2


def test_keyed_limiter_rejects_invalid_cost_without_adding_a_key():
    limiter = KeyedLimiter(2, 1.0, clock=FakeClock())

    with pytest.raises(ValueError):
        limiter.allow("new", cost=0)
    assert len(limiter) == 0
