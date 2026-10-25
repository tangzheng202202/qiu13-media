import threading
import time
from collections import OrderedDict

_MISSING = object()


class _KeyLock:
    """A lock with a reference count, so idle per-key locks can be removed."""

    __slots__ = ("lock", "refs")

    def __init__(self):
        self.lock = threading.Lock()
        self.refs = 0


class Cache:
    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        if default_ttl is not None and not default_ttl > 0:
            raise ValueError("default_ttl must be greater than 0")

        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock
        self._data = OrderedDict()  # key -> (value, expires_at or None)
        self._lock = threading.Lock()
        self._key_locks = {}
        self._hits = self._misses = self._evictions = 0

    def _resolve_ttl(self, ttl):
        if ttl is None:
            ttl = self.default_ttl
        if ttl is not None and not ttl > 0:
            raise ValueError("ttl must be greater than 0")
        return ttl

    @staticmethod
    def _expired(expires_at, now):
        return expires_at is not None and now >= expires_at

    def _purge_expired(self, now):
        expired = [
            key
            for key, (_, expires_at) in self._data.items()
            if self._expired(expires_at, now)
        ]
        for key in expired:
            del self._data[key]

    def _live_item(self, key, now):
        """Return a live item, removing this key if it has expired."""
        item = self._data.get(key)
        if item is not None and self._expired(item[1], now):
            del self._data[key]
            return None
        return item

    def _set_resolved(self, key, value, ttl):
        """Set an item whose TTL has already been resolved and validated."""
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            expires_at = None if ttl is None else now + ttl

            if key not in self._data:
                while len(self._data) >= self.maxsize:
                    self._data.popitem(last=False)
                    self._evictions += 1

            self._data[key] = (value, expires_at)
            self._data.move_to_end(key)

    def set(self, key, value, ttl=None):
        self._set_resolved(key, value, self._resolve_ttl(ttl))

    def get(self, key, default=None):
        with self._lock:
            item = self._live_item(key, self.clock())
            if item is None:
                self._misses += 1
                return default

            self._hits += 1
            self._data.move_to_end(key)
            return item[0]

    def peek(self, key, default=None):
        with self._lock:
            item = self._live_item(key, self.clock())
            if item is None:
                return default
            return item[0]

    def __contains__(self, key):
        with self._lock:
            return self._live_item(key, self.clock()) is not None

    def __len__(self):
        with self._lock:
            self._purge_expired(self.clock())
            return len(self._data)

    def keys(self):
        with self._lock:
            self._purge_expired(self.clock())
            return list(self._data.keys())

    def items(self):
        with self._lock:
            self._purge_expired(self.clock())
            return [(key, value) for key, (value, _) in self._data.items()]

    def pop(self, key, default=_MISSING):
        with self._lock:
            item = self._live_item(key, self.clock())
            if item is not None:
                del self._data[key]
                return item[0]

            if default is _MISSING:
                raise KeyError(key)
            return default

    def _retain_key_lock(self, key):
        with self._lock:
            key_lock = self._key_locks.get(key)
            if key_lock is None:
                key_lock = _KeyLock()
                self._key_locks[key] = key_lock
            key_lock.refs += 1
            return key_lock

    def _release_key_lock(self, key, key_lock):
        # Release the per-key lock before dropping its last reference.  That
        # prevents a new caller from entering a replacement lock too early.
        key_lock.lock.release()
        with self._lock:
            key_lock.refs -= 1
            if key_lock.refs == 0 and self._key_locks.get(key) is key_lock:
                del self._key_locks[key]

    def get_or_set(self, key, factory, ttl=None):
        # Validate before calling user code.  Resolving here also ensures that
        # a factory is never run for an invalid TTL.
        resolved_ttl = self._resolve_ttl(ttl)
        key_lock = self._retain_key_lock(key)
        key_lock.lock.acquire()
        try:
            # Only this per-key lock is held while checking and computing a
            # missing value.  In particular, the cache-wide lock is never held
            # while factory() runs.
            with self._lock:
                item = self._live_item(key, self.clock())
                if item is not None:
                    self._hits += 1
                    self._data.move_to_end(key)
                    return item[0]
                self._misses += 1

            value = factory()
            self._set_resolved(key, value, resolved_ttl)
            return value
        finally:
            self._release_key_lock(key, key_lock)

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def _remaining(self):
        """Return a locked snapshot of (key, value, remaining TTL) tuples."""
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return [
                (key, value, None if expires_at is None else expires_at - now)
                for key, (value, expires_at) in self._data.items()
            ]
