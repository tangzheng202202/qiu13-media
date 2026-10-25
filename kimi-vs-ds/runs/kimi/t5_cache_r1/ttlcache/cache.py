import threading
import time
from collections import OrderedDict


_MISSING = object()


def _validate_ttl(ttl):
    """Return *ttl*, rejecting values which are not greater than zero."""
    if ttl is not None and not ttl > 0:
        raise ValueError("ttl must be greater than 0")
    return ttl


class _Flight:
    """The state shared by callers waiting for one get_or_set factory."""

    __slots__ = ("event", "value", "error")

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.error = None


class Cache:
    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        if not maxsize >= 1:
            raise ValueError("maxsize must be at least 1")
        _validate_ttl(default_ttl)

        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock
        self._data = OrderedDict()  # key -> (value, expires_at or None)
        self._lock = threading.Lock()
        self._hits = self._misses = self._evictions = 0

        # A factory runs without the cache-wide lock.  Only callers computing
        # the same missing key wait on its flight.
        self._flights = {}

    def _effective_ttl(self, ttl):
        if ttl is None:
            ttl = self.default_ttl
        return _validate_ttl(ttl)

    @staticmethod
    def _is_expired(expires_at, now):
        return expires_at is not None and now >= expires_at

    def _purge_expired(self, now):
        expired = [
            key
            for key, (_, expires_at) in self._data.items()
            if self._is_expired(expires_at, now)
        ]
        for key in expired:
            del self._data[key]

    def _set_locked(self, key, value, ttl):
        """Set an already validated, effective TTL; self._lock must be held."""
        now = self.clock()
        self._purge_expired(now)
        expires_at = None if ttl is None else now + ttl

        if key in self._data:
            self._data[key] = (value, expires_at)
            self._data.move_to_end(key)
            return

        # Expired entries have already been removed, so only live entries can
        # be evicted here.  OrderedDict's first item is the LRU entry.
        while len(self._data) + 1 > self.maxsize:
            if not self._data:
                # This can only be reached if maxsize was mutated directly to
                # an invalid value after construction.
                raise ValueError("maxsize must be at least 1")
            self._data.popitem(last=False)
            self._evictions += 1

        self._data[key] = (value, expires_at)

    def set(self, key, value, ttl=None):
        ttl = self._effective_ttl(ttl)
        with self._lock:
            self._set_locked(key, value, ttl)

    def get(self, key, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return default

            if self._is_expired(item[1], self.clock()):
                del self._data[key]
                self._misses += 1
                return default

            self._data.move_to_end(key)
            self._hits += 1
            return item[0]

    def peek(self, key, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            if self._is_expired(item[1], self.clock()):
                del self._data[key]
                return default
            return item[0]

    def __contains__(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return False
            if self._is_expired(item[1], self.clock()):
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
            item = self._data.get(key)
            if item is not None:
                if self._is_expired(item[1], self.clock()):
                    del self._data[key]
                else:
                    self._data.pop(key)
                    return item[0]

            if default is _MISSING:
                raise KeyError(key)
            return default

    def get_or_set(self, key, factory, ttl=None):
        # Validate before either invoking a factory or modifying cache stats.
        ttl = self._effective_ttl(ttl)
        owner = False

        with self._lock:
            item = self._data.get(key)
            if item is not None:
                if self._is_expired(item[1], self.clock()):
                    del self._data[key]
                else:
                    self._data.move_to_end(key)
                    self._hits += 1
                    return item[0]

            self._misses += 1
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight()
                self._flights[key] = flight
                owner = True

        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value

        try:
            value = factory()
            with self._lock:
                self._set_locked(key, value, ttl)
                flight.value = value
                # Installation and publication are atomic with respect to new
                # get_or_set callers, preventing a duplicate factory call.
                del self._flights[key]
        except BaseException as exc:
            with self._lock:
                if self._flights.get(key) is flight:
                    del self._flights[key]
                flight.error = exc
            flight.event.set()
            raise

        flight.event.set()
        return value

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def _remaining(self):
        """Return a consistent live snapshot with TTLs relative to one now."""
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            return [
                (key, value, None if expires_at is None else expires_at - now)
                for key, (value, expires_at) in self._data.items()
            ]
