import json
import os
import tempfile

from .cache import Cache


def save(cache, path):
    """Atomically persist the live entries of ``cache`` to ``path``.

    The file is written to a temporary file in the same directory and then
    moved into place with ``os.replace``.  Only live entries are stored, in
    LRU -> MRU order, with their *remaining* TTL (or ``None`` for entries that
    never expire).
    """
    entries = [{"k": k, "v": v, "exp": rem} for k, v, rem in cache._remaining()]
    payload = {"entries": entries}

    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".ttlcache-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
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

    Entries are restored in the same LRU -> MRU order with their remaining
    TTLs taken relative to the new clock.  If ``maxsize`` is smaller than the
    number of saved entries the most recently used ones are kept.
    """
    if maxsize < 1:
        raise ValueError("maxsize must be >= 1")

    with open(path) as f:
        data = json.load(f)

    cache = Cache(maxsize) if clock is None else Cache(maxsize, clock=clock)

    entries = data.get("entries", [])
    # Entries are stored LRU first, so the most recently used are at the end.
    if len(entries) > maxsize:
        entries = entries[len(entries) - maxsize:]

    for e in entries:
        key = e["k"] if "k" in e else e["key"]
        value = e["v"] if "v" in e else e["value"]
        rem = e.get("exp", e.get("ttl"))
        if rem is not None and rem <= 0:
            # Not live any more; never save/restore expired entries.
            continue
        if rem is None:
            cache.set(key, value)
        else:
            cache.set(key, value, ttl=rem)

    return cache
