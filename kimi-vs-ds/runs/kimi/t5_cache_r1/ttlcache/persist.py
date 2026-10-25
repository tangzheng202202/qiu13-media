import json
import os
import tempfile

from .cache import Cache


def save(cache, path):
    # _remaining takes the cache lock and snapshots values, LRU order, and all
    # remaining TTLs against the same clock reading.
    entries = [
        {"k": key, "v": value, "exp": remaining}
        for key, value, remaining in cache._remaining()
    ]

    target = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(target)
    if isinstance(target, bytes):
        prefix = b"." + os.path.basename(target) + b"."
        suffix = b".tmp"
    else:
        prefix = "." + os.path.basename(target) + "."
        suffix = ".tmp"

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=prefix,
            suffix=suffix,
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump({"entries": entries}, stream)
            stream.flush()
            os.fsync(stream.fileno())

        # The temporary file is in the target's directory, so replacement is
        # atomic and readers never observe a partially written JSON document.
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def load(path, maxsize, clock=None):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)

    cache = Cache(maxsize) if clock is None else Cache(maxsize, clock=clock)

    # Saved entries are LRU -> MRU.  Inserting in that order both preserves
    # recency and naturally retains the MRU entries when maxsize is smaller.
    for entry in data["entries"]:
        cache.set(entry["k"], entry["v"], ttl=entry["exp"])
    return cache
