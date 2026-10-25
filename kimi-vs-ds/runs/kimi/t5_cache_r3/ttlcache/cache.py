import threading
import time
from collections import OrderedDict

_MISSING = object()


def _validate_ttl(ttl):
    """Validate an effective TTL, allowing None for entries without expiry."""
    if ttl is None:
        return
    try:
        valid = ttl > 0
    except TypeError as exc:
        raise ValueError("ttl must be greater than zero") from exc
    if not valid:
        raise ValueError("ttl must be greater than zero")


class _KeyLock:
    """A lock with a reference count, used to serialize factories per key."""

    def __init__(self):
        self.lock = threading.Lock()
        self.users = 0


class Cache:
    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        _validate_ttl(default_ttl)

        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock
        # Ordered from least recently used to most recently used.
        self._data = OrderedDict()  # key -> (value, expires_at or None)
        self._lock = threading.RLock()
        self._key_locks = {}
        self._hits = self._misses = self._evictions = 0

    def _expired(self, exp, now=None):
        if exp is None:
            return False
        if now is None:
            now = self.clock()
        return now >= exp

    def _purge_expired(self, now):
        """Remove expired entries. The caller must hold ``_lock``."""
        expired = [
            key
            for key, (_, exp) in self._data.items()
            if self._expired(exp, now)
        ]
        for key in expired:
            del self._data[key]

    def _effective_ttl(self, ttl):
        if ttl is None:
            ttl = self.default_ttl
        _validate_ttl(ttl)
        return ttl

    def set(self, key, value, ttl=None):
        ttl = self._effective_ttl(ttl)
        with self._lock:
            now = self.clock()
            exp = None if ttl is None else now + ttl
            self._purge_expired(now)

            if key in self._data:
                self._data[key] = (value, exp)
                self._data.move_to_end(key)
                return

            # Expiration is not eviction and must not affect the eviction count.
            while len(self._data) >= self.maxsize:
                self._data.popitem(last=False)
                self._evictions += 1
            self._data[key] = (value, exp)

    def get(self, key, default=None):
        with self._lock:
            item = self._data.get(key, _MISSING)
            if item is _MISSING:
                self._misses += 1
                return default
            if self._expired(item[1]):
                del self._data[key]
                self._misses += 1
                return default

            self._hits += 1
            self._data.move_to_end(key)
            return item[0]

    def peek(self, key, default=None):
        with self._lock:
            item = self._data.get(key, _MISSING)
            if item is _MISSING:
                return default
            if self._expired(item[1]):
                del self._data[key]
                return default
            return item[0]

    def __contains__(self, key):
        with self._lock:
            item = self._data.get(key, _MISSING)
            if item is _MISSING:
                return False
            if self._expired(item[1]):
                del self._data[key]
                return False
            return True

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
            item = self._data.get(key, _MISSING)
            if item is not _MISSING:
                expired = self._expired(item[1])
                del self._data[key]
                if not expired:
                    return item[0]

            if default is _MISSING:
                raise KeyError(key)
            return default

    def _acquire_key_lock(self, key):
        # The reference count includes both the holder and threads waiting for
        # the lock, so an entry can safely be removed when it reaches zero.
        with self._lock:
            entry = self._key_locks.get(key)
            if entry is None:
                entry = _KeyLock()
                self._key_locks[key] = entry
            entry.users += 1
        entry.lock.acquire()
        return entry

    def _release_key_lock(self, key, entry):
        # Remove an unused entry before unlocking it. The cache operation is
        # already complete at this point, so a subsequent caller may safely
        # create a new entry even if it runs just before the unlock below.
        with self._lock:
            entry.users -= 1
            if entry.users == 0 and self._key_locks.get(key) is entry:
                del self._key_locks[key]
        entry.lock.release()

    def get_or_set(self, key, factory, ttl=None):
        entry = self._acquire_key_lock(key)
        try:
            missing = object()
            value = self.get(key, missing)
            if value is not missing:
                return value

            # Reject an invalid TTL before doing potentially expensive work.
            self._effective_ttl(ttl)
            value = factory()
            # The global cache lock is never held while running user code.
            self.set(key, value, ttl)
            return value
        finally:
            self._release_key_lock(key, entry)

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
                (key, value, None if exp is None else exp - now)
                for key, (value, exp) in self._data.items()
            ]
