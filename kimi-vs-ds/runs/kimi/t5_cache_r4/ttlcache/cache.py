"""A thread-safe LRU cache with optional per-entry expiration times."""

import threading
import time
from collections import OrderedDict


_MISSING = object()


def _validate_ttl(ttl):
    """Validate a TTL, returning it for convenient use by callers.

    ``None`` is the only value which means that an entry does not expire.
    In particular, zero must not be treated as a false-y substitute for the
    cache's default TTL.
    """
    if ttl is not None and not ttl > 0:
        raise ValueError("ttl must be greater than 0")
    return ttl


class Cache:
    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        if not maxsize >= 1:
            raise ValueError("maxsize must be at least 1")
        _validate_ttl(default_ttl)

        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock
        self._data = OrderedDict()  # key -> (value, expires_at or None)
        # The cache lock is never held while a get_or_set factory runs.
        self._lock = threading.RLock()
        # A lock per key serializes get_or_set calls without serializing
        # factories for unrelated keys.  Locks are intentionally retained:
        # removing one while another thread is waiting for it could allow two
        # different locks (and therefore two factories) for the same key.
        self._key_locks = {}
        self._key_locks_guard = threading.Lock()
        self._hits = self._misses = self._evictions = 0

    def _expired(self, exp, now=None):
        if exp is None:
            return False
        if now is None:
            now = self.clock()
        return now >= exp

    def _purge_expired(self, now):
        """Remove expired entries.  The cache lock must be held."""
        expired = [
            key
            for key, (_value, exp) in self._data.items()
            if self._expired(exp, now)
        ]
        for key in expired:
            del self._data[key]

    def _effective_ttl(self, ttl):
        return _validate_ttl(self.default_ttl if ttl is None else ttl)

    def _key_lock(self, key):
        # This guard is separate from _lock so that looking up a key lock does
        # not add any work to the cache's critical sections.  No cache
        # operation holds this guard while waiting for a per-key lock.
        with self._key_locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def _lookup_locked(self, key, now):
        """Return ``(found, value)`` and update recency; lock is held."""
        self._purge_expired(now)
        item = self._data.get(key)
        if item is None:
            return False, None
        self._data.move_to_end(key)
        return True, item[0]

    def set(self, key, value, ttl=None):
        effective_ttl = self._effective_ttl(ttl)
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            expires_at = None if effective_ttl is None else now + effective_ttl

            if key in self._data:
                self._data[key] = (value, expires_at)
                self._data.move_to_end(key)
                return

            # Expired entries have already been removed, so only live entries
            # participate in the capacity decision.  Evict from the LRU end.
            while len(self._data) + 1 > self.maxsize:
                self._data.popitem(last=False)
                self._evictions += 1
            self._data[key] = (value, expires_at)

    def get(self, key, default=None):
        with self._lock:
            found, value = self._lookup_locked(key, self.clock())
            if not found:
                self._misses += 1
                return default
            self._hits += 1
            return value

    def peek(self, key, default=None):
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            item = self._data.get(key)
            if item is None:
                return default
            # Unlike get(), peek deliberately does not change LRU recency.
            return item[0]

    def __contains__(self, key):
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return key in self._data

    def __len__(self):
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return len(self._data)

    def keys(self):
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return list(self._data.keys())

    def items(self):
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return [(key, value) for key, (value, _exp) in self._data.items()]

    def pop(self, key, default=_MISSING):
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            item = self._data.pop(key, None)
            if item is not None:
                return item[0]
            if default is _MISSING:
                raise KeyError(key)
            return default

    def get_or_set(self, key, factory, ttl=None):
        # Validate before invoking user code.  This also makes an invalid TTL
        # an error even when the key already has a live value.
        self._effective_ttl(ttl)
        key_lock = self._key_lock(key)
        with key_lock:
            # Do not hold the cache-wide lock while running user code.  The
            # lookup itself is still done under that lock, and the per-key
            # lock makes concurrent get_or_set calls share one factory.
            with self._lock:
                found, value = self._lookup_locked(key, self.clock())
                if found:
                    self._hits += 1
                    return value
                self._misses += 1

            value = factory()
            self.set(key, value, ttl)
            return value

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def _remaining(self):
        """Return a consistent snapshot of live entries and remaining TTLs."""
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return [
                (key, value, None if exp is None else exp - now)
                for key, (value, exp) in self._data.items()
            ]
