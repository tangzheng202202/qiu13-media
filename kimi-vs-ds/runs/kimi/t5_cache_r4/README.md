# ttlcache — thread-safe LRU cache with per-key TTL and snapshot persistence
Modules: `ttlcache/clock.py`, `ttlcache/cache.py`, `ttlcache/persist.py`.
Intended behavior (the contract):
- `Cache(maxsize, default_ttl=None, clock=time.monotonic)`. `set(key, value, ttl=None)`; ttl None -> default_ttl; default None means never expires. ttl must be > 0 else ValueError.
- An entry is expired when `clock() >= expires_at`. Expired entries behave as absent everywhere (`get`, `in`, `len`, `keys()`, `items()`), and are never counted toward maxsize when deciding eviction.
- `get(key, default=None)` marks key as most recently used. `set` on existing key updates value/ttl and marks MRU. `peek(key)` returns value without touching recency.
- When inserting a new key would exceed `maxsize`, first purge expired entries, then evict LRU until it fits. `maxsize` must be >= 1.
- `pop(key, default=_MISSING)` removes and returns; raises KeyError if absent and no default. `stats()` returns dict hits/misses/evictions (evictions counts only LRU evictions, not expirations).
- `get_or_set(key, factory, ttl=None)`: atomic: under concurrency, factory is called at most once per key while it is live.
- `keys()` and `items()` return live entries in LRU -> MRU order.
- All public methods are thread-safe; a slow `get_or_set` factory must not block operations on other keys.
- `persist.save(cache, path)` writes JSON atomically (write to temp file in same dir then os.replace); stores remaining TTL (not absolute monotonic time) for each live entry, and preserves LRU order; JSON top-level object has key `entries` (list, LRU first). Expired entries are not saved. If `maxsize` on load is smaller, keep the most recently used entries. `persist.load(path, maxsize, clock=...)` returns a new Cache with entries restored in the same LRU order with their remaining TTLs relative to the new clock. Values are JSON-serializable. Keys are strings.
Users report several bugs. The existing tests in `tests/` are incomplete.
