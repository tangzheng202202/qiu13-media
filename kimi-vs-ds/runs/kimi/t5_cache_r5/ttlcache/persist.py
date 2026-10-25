import json
import os
import tempfile

from .cache import Cache


def save(cache, path):
    # Take one cache snapshot so every remaining TTL uses the same instant and
    # the entry order is internally consistent.
    entries = [
        {"k": key, "v": value, "exp": remaining}
        for key, value, remaining in cache._remaining()
    ]

    target = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(target))
    fd, temporary = tempfile.mkstemp(
        dir=directory, prefix=".ttlcache-", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"entries": entries}, stream)
        os.replace(temporary, target)
    except BaseException:
        # A failed dump or replace must not leave temporary files behind or
        # disturb an existing snapshot.
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load(path, maxsize, clock=None):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)

    cache = Cache(maxsize) if clock is None else Cache(maxsize, clock=clock)
    # Entries are serialized LRU first.  Inserting in that order both restores
    # recency and naturally retains the MRU tail when maxsize is smaller.
    for entry in data["entries"]:
        cache.set(entry["k"], entry["v"], ttl=entry["exp"])
    return cache
