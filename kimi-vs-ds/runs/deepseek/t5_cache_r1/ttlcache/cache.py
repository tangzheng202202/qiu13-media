import threading
import time
from collections import OrderedDict

_MISSING = object()


class Cache:
    """Thread-safe LRU cache with per-key TTL."""

    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("ttl must be > 0")
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock
        # key -> (value, expires_at or None); iteration order is LRU -> MRU.
        self._data = OrderedDict()
        self._lock = threading.Lock()
        # Per-key locks used to make get_or_set atomic without serializing
        # unrelated keys behind a slow factory.
        self._key_locks = {}
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # ------------------------------------------------------------------
    # internal helpers (callers must hold self._lock unless noted otherwise)
    # ------------------------------------------------------------------
    def _expired(self, expires_at):
        return expires_at is not None and self.clock() >= expires_at

    def _resolve_expiry(self, ttl):
        """Validate *ttl* and turn it into an absolute expiry timestamp."""
        if ttl is None:
            ttl = self.default_ttl
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0")
        return None if ttl is None else self.clock() + ttl

    def _purge_expired_locked(self):
        if not self._data:
            return
        now = self.clock()
        expired = [
            k for k, (_, expires_at) in self._data.items()
            if expires_at is not None and now >= expires_at
        ]
        for k in expired:
            del self._data[k]

    def _get_locked(self, key, default):
        item = self._data.get(key)
        if item is None or self._expired(item[1]):
            if item is not None:
                # An expired entry is semantically absent; drop it lazily.
                del self._data[key]
            self._misses += 1
            return default
        self._hits += 1
        self._data.move_to_end(key)
        return item[0]

    def _set_locked(self, key, value, ttl=None):
        expires_at = self._resolve_expiry(ttl)
        if key in self._data:
            # Updating an existing key does not need to make room and must
            # refresh its recency.
            self._data[key] = (value, expires_at)
            self._data.move_to_end(key)
            return

        # Inserting a new key: expired entries never count toward maxsize,
        # so purge them before deciding whether to evict.
        self._purge_expired_locked()
        while len(self._data) >= self.maxsize:
            self._data.popitem(last=False)  # evict least recently used
            self._evictions += 1
        self._data[key] = (value, expires_at)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def set(self, key, value, ttl=None):
        with self._lock:
            self._set_locked(key, value, ttl)

    def get(self, key, default=None):
        with self._lock:
            return self._get_locked(key, default)

    def peek(self, key, default=None):
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
            return sum(
                1
                for _, expires_at in self._data.values()
                if expires_at is None or now < expires_at
            )

    def keys(self):
        with self._lock:
            now = self.clock()
            return [
                k
                for k, (_, expires_at) in self._data.items()
                if expires_at is None or now < expires_at
            ]

    def items(self):
        with self._lock:
            now = self.clock()
            return [
                (k, v)
                for k, (v, expires_at) in self._data.items()
                if expires_at is None or now < expires_at
            ]

    def pop(self, key, default=_MISSING):
        with self._lock:
            item = self._data.get(key)
            if item is None or self._expired(item[1]):
                if item is not None:
                    del self._data[key]
                if default is _MISSING:
                    raise KeyError(key)
                return default
            del self._data[key]
            return item[0]

    def get_or_set(self, key, factory, ttl=None):
        # Validate eagerly so an invalid ttl is rejected even when the key is
        # already live.
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0")

        with self._lock:
            item = self._data.get(key)
            if item is not None and not self._expired(item[1]):
                self._hits += 1
                self._data.move_to_end(key)
                return item[0]
            self._misses += 1
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock

        # Only one thread at a time may compute the value for *key*.  The
        # global cache lock is not held here, so a slow factory cannot block
        # operations on other keys.
        with lock:
            with self._lock:
                item = self._data.get(key)
                if item is not None and not self._expired(item[1]):
                    # Another thread populated the key while we waited.
                    self._data.move_to_end(key)
                    return item[0]

            value = factory()

            with self._lock:
                self._set_locked(key, value, ttl)
            return value

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    # ------------------------------------------------------------------
    # persistence support
    # ------------------------------------------------------------------
    def _remaining(self):
        """Return ``(key, value, remaining_ttl)`` for live entries, LRU first."""
        with self._lock:
            now = self.clock()
            return [
                (k, v, None if expires_at is None else expires_at - now)
                for k, (v, expires_at) in self._data.items()
                if expires_at is None or now < expires_at
            ]
