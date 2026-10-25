import json
import os
import tempfile
import time

from .cache import Cache


def save(cache, path):
    """Persist *cache* to *path* atomically as JSON.

    Only live entries are written, in LRU -> MRU order, storing the
    remaining TTL (relative to the cache's clock) rather than an absolute
    timestamp.
    """
    entries = [
        {"k": key, "v": value, "exp": remaining}
        for key, value, remaining in cache._remaining()
    ]

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".ttlcache-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load(path, maxsize, clock=None):
    """Load a cache previously written by :func:`save`.

    Entries are restored in their original LRU order.  If *maxsize* is
    smaller than the number of saved entries, the most recently used ones
    are kept.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["entries"]

    # Defensive: skip entries whose TTL has already elapsed.  Normally save()
    # never writes those, but hand-edited files should still load cleanly.
    live = [
        e for e in entries
        if e.get("exp") is None or e["exp"] > 0
    ]
    if maxsize < len(live):
        live = live[-maxsize:]

    if clock is None:
        cache = Cache(maxsize)
    else:
        cache = Cache(maxsize, clock=clock)

    for entry in live:
        cache.set(entry["k"], entry["v"], ttl=entry.get("exp"))
    return cache
