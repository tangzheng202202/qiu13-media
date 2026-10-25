"""Token-bucket rate limiting primitives.

This module provides two small, dependency-free building blocks:

``TokenBucket``
    A classic token bucket: ``capacity`` tokens that refill continuously at
    ``refill_rate`` tokens per second and are consumed by callers.

``KeyedLimiter``
    A mapping of independent token buckets, one per key, with a bounded
    number of tracked keys and least-recently-used eviction.

Both classes accept an injectable ``clock`` callable (defaulting to
``time.monotonic``) returning the current time in seconds, which makes them
straightforward to test deterministically.

Example
-------
>>> clock = lambda: 0.0
>>> bucket = TokenBucket(capacity=2, refill_rate=1.0, clock=clock)
>>> bucket.allow(2)
True
>>> bucket.allow()
False
>>> bucket.wait_time(1)
1.0
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from typing import Callable, Hashable, Optional

__all__ = ["TokenBucket", "KeyedLimiter"]

# Relative/absolute slack used when comparing token counts.  Refilling is
# floating point arithmetic, so a caller who waits exactly ``wait_time()``
# seconds may otherwise end up a rounding error short of the requested cost.
_REL_TOL = 1e-12
_ABS_TOL = 1e-12


def _validate_cost(cost: float, capacity: float) -> None:
    """Validate a requested cost against ``capacity``.

    A cost that is not positive, or that exceeds the capacity of the bucket,
    can never be satisfied and is therefore rejected with ``ValueError``.
    """
    if cost <= 0:
        raise ValueError(f"cost must be positive, got {cost!r}")
    if cost > capacity:
        raise ValueError(f"cost ({cost!r}) exceeds capacity ({capacity!r})")


def _covers(tokens: float, cost: float) -> bool:
    """Return whether ``tokens`` are enough to pay for ``cost``."""
    return tokens >= cost or math.isclose(
        tokens, cost, rel_tol=_REL_TOL, abs_tol=_ABS_TOL
    )


class TokenBucket:
    """A continuously-refilling token bucket.

    Parameters
    ----------
    capacity:
        Maximum number of tokens the bucket can hold.  The bucket starts full.
    refill_rate:
        Tokens added per second.
    clock:
        Callable returning the current time in seconds.  Defaults to
        :func:`time.monotonic`.
    """

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.clock = clock

        # The bucket starts full.
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = threading.RLock()

    # -- internals ---------------------------------------------------------

    def _refill(self) -> None:
        """Add tokens for the time elapsed since the last update."""
        now = self.clock()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(
                float(self.capacity), self._tokens + elapsed * self.refill_rate
            )
            self._last = now
        elif elapsed < 0:
            # A clock that moves backwards: resynchronise without refilling.
            self._last = now

    # -- public API --------------------------------------------------------

    @property
    def tokens(self) -> float:
        """Current number of tokens, after applying any pending refill."""
        with self._lock:
            self._refill()
            return self._tokens

    def allow(self, cost: int = 1) -> bool:
        """Try to consume ``cost`` tokens.

        Returns ``True`` and consumes the tokens if enough are available,
        otherwise returns ``False`` and leaves the bucket untouched.
        Raises ``ValueError`` if ``cost`` is not positive or exceeds the
        bucket capacity.
        """
        _validate_cost(cost, self.capacity)
        with self._lock:
            self._refill()
            if not _covers(self._tokens, cost):
                return False
            self._tokens = max(0.0, self._tokens - cost)
            return True

    def wait_time(self, cost: int = 1) -> float:
        """Seconds until ``allow(cost)`` would succeed (``0.0`` if now)."""
        _validate_cost(cost, self.capacity)
        with self._lock:
            self._refill()
            missing = cost - self._tokens
            if missing <= 0 or _covers(self._tokens, cost):
                return 0.0
            if self.refill_rate <= 0:
                # The bucket will never refill.
                return math.inf
            return missing / self.refill_rate

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{type(self).__name__}(capacity={self.capacity!r}, "
            f"refill_rate={self.refill_rate!r}, tokens={self.tokens!r})"
        )


class KeyedLimiter:
    """A collection of independent :class:`TokenBucket` instances by key.

    Each key gets its own bucket, so limits are enforced independently per
    key.  At most ``max_keys`` buckets are tracked; adding a new key once the
    limit is reached evicts the least-recently-used key.

    Parameters
    ----------
    capacity, refill_rate:
        Forwarded to each per-key :class:`TokenBucket`.
    clock:
        Callable returning the current time in seconds, shared by all
        buckets.  Defaults to :func:`time.monotonic`.
    max_keys:
        Maximum number of keys to track.  ``None`` means unlimited.
    """

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: Optional[int] = 1000,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.clock = clock
        self.max_keys = max_keys
        # Ordered from least to most recently used.
        self._buckets: "OrderedDict[Hashable, TokenBucket]" = OrderedDict()
        self._lock = threading.RLock()

    # -- internals ---------------------------------------------------------

    def _get_or_create(self, key: Hashable) -> TokenBucket:
        """Return ``key``'s bucket, marking the key as most recently used."""
        bucket = self._buckets.get(key)
        if bucket is not None:
            self._buckets.move_to_end(key)
            return bucket

        bucket = TokenBucket(self.capacity, self.refill_rate, self.clock)
        if self.max_keys is None or self.max_keys > 0:
            self._buckets[key] = bucket
            while self.max_keys is not None and len(self._buckets) > self.max_keys:
                # Drop the least recently used key.
                self._buckets.popitem(last=False)
        # With ``max_keys == 0`` nothing can be tracked; the freshly created
        # bucket still serves this call but is not retained.
        return bucket

    # -- public API --------------------------------------------------------

    def allow(self, key: Hashable, cost: int = 1) -> bool:
        """Consume ``cost`` tokens from ``key``'s bucket.

        The key is marked as most recently used on every call.
        """
        _validate_cost(cost, self.capacity)
        with self._lock:
            return self._get_or_create(key).allow(cost)

    def wait_time(self, key: Hashable, cost: int = 1) -> float:
        """Seconds until ``allow(key, cost)`` would succeed (``0.0`` if now)."""
        _validate_cost(cost, self.capacity)
        with self._lock:
            return self._get_or_create(key).wait_time(cost)

    def __len__(self) -> int:
        """Number of keys currently tracked."""
        with self._lock:
            return len(self._buckets)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._buckets

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{type(self).__name__}(capacity={self.capacity!r}, "
            f"refill_rate={self.refill_rate!r}, max_keys={self.max_keys!r}, "
            f"keys={len(self)!r})"
        )
