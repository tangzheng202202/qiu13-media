import threading
import time
from collections import OrderedDict

_MISSING = object()


class Cache:
    """Thread-safe LRU cache with per-key TTL.

    An entry expires as soon as ``clock() >= expires_at``.  Expired entries
    behave as if they were absent for every public operation and never count
    towards ``maxsize``.
    """

    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("default_ttl must be > 0")
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock if clock is not None else time.monotonic
        self._data = OrderedDict()  # key -> (value, expires_at or None), LRU -> MRU
        self._lock = threading.RLock()
        self._hits = self._misses = self._evictions = 0
        # In-flight get_or_set computations: key -> threading.Event
        self._inflight = {}

    # -- internal helpers (all require the lock) --------------------------
    def _expired(self, exp, now=None):
        if exp is None:
            return False
        if now is None:
            now = self.clock()
        return now >= exp

    def _purge_expired(self, now):
        """Drop every expired entry.  Returns the number removed."""
        if not self._data:
            return 0
        dead = [k for k, (v, e) in self._data.items() if self._expired(e, now)]
        for k in dead:
            del self._data[k]
        return len(dead)

    # -- public API -------------------------------------------------------
    def set(self, key, value, ttl=None):
        if ttl is None:
            ttl = self.default_ttl
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0")
        with self._lock:
            now = self.clock()
            exp = None if ttl is None else now + ttl
            # Expired entries must not consume capacity nor cause evictions.
            self._purge_expired(now)
            if key in self._data:
                self._data[key] = (value, exp)
                self._data.move_to_end(key)
                return
            while len(self._data) >= self.maxsize:
                self._data.popitem(last=False)  # evict LRU
                self._evictions += 1
            self._data[key] = (value, exp)

    def get(self, key, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return default
            if self._expired(item[1]):
                del self._data[key]
                self._misses += 1
                return default
            self._data.move_to_end(key)
            self._hits += 1
            return item[0]

    def peek(self, key, default=None):
        """Return the value without touching recency."""
        with self._lock:
            item = self._data.get(key)
            if item is None or self._expired(item[1]):
                return default
            return item[0]

    def __contains__(self, key):
        with self._lock:
            item = self._data.get(key)
            return item is not None and not self._expired(item[1])

    def __len__(self):
        with self._lock:
            now = self.clock()
            return sum(1 for (v, e) in self._data.values() if not self._expired(e, now))

    def keys(self):
        """Live keys in LRU -> MRU order."""
        with self._lock:
            now = self.clock()
            return [k for k, (v, e) in self._data.items() if not self._expired(e, now)]

    def items(self):
        """Live (key, value) pairs in LRU -> MRU order."""
        with self._lock:
            now = self.clock()
            return [
                (k, v)
                for k, (v, e) in self._data.items()
                if not self._expired(e, now)
            ]

    def pop(self, key, default=_MISSING):
        with self._lock:
            item = self._data.pop(key, None)
            live = item is not None and not self._expired(item[1])
            if live:
                return item[0]
            if default is _MISSING:
                raise KeyError(key)
            return default

    def get_or_set(self, key, factory, ttl=None):
        if ttl is None:
            ttl = self.default_ttl
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0")

        with self._lock:
            item = self._data.get(key)
            if item is not None and not self._expired(item[1]):
                self._data.move_to_end(key)
                self._hits += 1
                return item[0]
            if item is not None:
                del self._data[key]
            self._misses += 1
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event()
                self._inflight[key] = event
                leader = True
            else:
                leader = False

        if not leader:
            # Another thread is already computing this key: wait for it.  A
            # slow factory therefore never blocks operations on other keys.
            event.wait()
            with self._lock:
                item = self._data.get(key)
                if item is not None and not self._expired(item[1]):
                    return item[0]
            # The leader failed (or its value already expired); retry.
            return self.get_or_set(key, factory, ttl)

        try:
            value = factory()
            self.set(key, value, ttl)
            return value
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            event.set()

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    # -- persistence helper ----------------------------------------------
    def _remaining(self):
        """Live entries as ``(key, value, remaining_ttl_or_None)`` in LRU order.

        Expired entries are skipped and remaining TTLs are expressed relative
        to the cache's clock (never the absolute ``expires_at``).
        """
        with self._lock:
            now = self.clock()
            out = []
            for k, (v, e) in self._data.items():
                if e is None:
                    out.append((k, v, None))
                    continue
                rem = e - now
                if rem <= 0:
                    continue
                out.append((k, v, rem))
            return out
