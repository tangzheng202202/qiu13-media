# Spec: rate limiter module `ratelimit.py`
Implement class `TokenBucket(capacity: int, refill_rate: float, clock=time.monotonic)`.
- Starts full (`capacity` tokens). Tokens refill continuously at `refill_rate` tokens/second, never exceeding capacity.
- `allow(cost: int = 1) -> bool`: if enough tokens, consume `cost` and return True, else return False and consume nothing.
- `cost` > capacity raises ValueError; cost <= 0 raises ValueError.
- `wait_time(cost: int = 1) -> float`: seconds until `allow(cost)` would succeed (0.0 if now).
Implement `KeyedLimiter(capacity, refill_rate, clock=time.monotonic, max_keys=1000)`:
- `allow(key, cost=1)` uses an independent TokenBucket per key.
- Keeps at most `max_keys` buckets; when adding a new key beyond the limit, evict the least-recently-used key.
- `__len__` returns the number of tracked keys.
Write tests in `test_ratelimit.py` too.
