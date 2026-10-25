import threading, time
from collections import OrderedDict
_MISSING = object()

class Cache:
    def __init__(self, maxsize, default_ttl=None, clock=time.monotonic):
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.clock = clock
        self._data = OrderedDict()  # key -> (value, expires_at or None)
        self._lock = threading.Lock()
        self._hits = self._misses = self._evictions = 0

    def _expired(self, exp):
        return exp is not None and self.clock() > exp

    def set(self, key, value, ttl=None):
        ttl = ttl or self.default_ttl
        exp = None if ttl is None else self.clock() + ttl
        with self._lock:
            if key not in self._data and len(self._data) >= self.maxsize:
                k, _ = self._data.popitem(last=True)
                self._evictions += 1
            self._data[key] = (value, exp)

    def get(self, key, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None or self._expired(item[1]):
                self._misses += 1
                return default
            self._hits += 1
            return item[0]

    def peek(self, key, default=None):
        item = self._data.get(key)
        if item is None or self._expired(item[1]):
            return default
        self._data.move_to_end(key)
        return item[0]

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def keys(self):
        return [k for k, (v, e) in self._data.items() if not self._expired(e)]

    def items(self):
        return [(k, v) for k, (v, e) in self._data.items() if not self._expired(e)]

    def pop(self, key, default=_MISSING):
        with self._lock:
            if key in self._data:
                return self._data.pop(key)[0]
            if default is _MISSING:
                raise KeyError(key)
            return default

    def get_or_set(self, key, factory, ttl=None):
        v = self.get(key, _MISSING)
        if v is _MISSING:
            v = factory()
            self.set(key, v, ttl)
        return v

    def stats(self):
        return {"hits": self._hits, "misses": self._misses, "evictions": self._evictions}

    def _remaining(self):
        now = self.clock()
        return [(k, v, None if e is None else e - now) for k, (v, e) in self._data.items()]
