"""In-memory token-bucket rate limiters."""

from collections import OrderedDict
import time


__all__ = ["TokenBucket", "KeyedLimiter"]


def _validate_cost(cost, capacity):
    """Validate a request cost before changing any bucket state."""
    if cost <= 0:
        raise ValueError("cost must be greater than zero")
    if cost > capacity:
        raise ValueError("cost cannot exceed bucket capacity")


class TokenBucket:
    """A continuously refilling token bucket.

    The bucket starts full.  Refilling is calculated lazily from the supplied
    clock, so no background work is required.
    """

    def __init__(
        self, capacity: int, refill_rate: float, clock=time.monotonic
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.clock = clock
        self.tokens = float(capacity)
        self.last_refill = clock()

    def _refill(self):
        now = self.clock()
        elapsed = now - self.last_refill
        self.tokens = min(
            float(self.capacity),
            self.tokens + elapsed * self.refill_rate,
        )
        self.last_refill = now

    def allow(self, cost: int = 1) -> bool:
        """Consume *cost* tokens if they are available.

        An unsuccessful request leaves all currently available tokens in the
        bucket.  Elapsed time still contributes its normal refill.
        """
        _validate_cost(cost, self.capacity)
        self._refill()
        if self.tokens < cost:
            return False
        self.tokens -= cost
        return True

    def wait_time(self, cost: int = 1) -> float:
        """Return the number of seconds until *cost* tokens are available."""
        _validate_cost(cost, self.capacity)
        self._refill()
        if self.tokens >= cost:
            return 0.0
        if self.refill_rate <= 0:
            # With no positive refill, an insufficient bucket can never fill.
            return float("inf")
        return (cost - self.tokens) / self.refill_rate


class KeyedLimiter:
    """Maintain an independent, LRU-bounded token bucket for each key."""

    def __init__(
        self, capacity, refill_rate, clock=time.monotonic, max_keys=1000
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.clock = clock
        self.max_keys = max_keys
        self._buckets = OrderedDict()

    def allow(self, key, cost=1):
        """Apply a request to *key*'s bucket and mark that key as recently used."""
        # Reject invalid requests without creating a key or evicting another.
        _validate_cost(cost, self.capacity)

        if key in self._buckets:
            bucket = self._buckets[key]
            self._buckets.move_to_end(key)
        else:
            bucket = TokenBucket(
                self.capacity, self.refill_rate, clock=self.clock
            )
            self._buckets[key] = bucket
            if len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)

        return bucket.allow(cost)

    def __len__(self):
        return len(self._buckets)
