import json
import os
import tempfile
import time

from .cache import Cache


def save(cache, path):
    """Atomically save a consistent snapshot of the cache as JSON."""
    entries = [
        {"k": key, "v": value, "exp": remaining}
        for key, value, remaining in cache._remaining()
    ]

    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    temp_path = None
    try:
        # The temporary file must be beside the destination for os.replace to
        # provide an atomic rename on the same filesystem.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".ttlcache-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            json.dump({"entries": entries}, temp_file)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def load(path, maxsize, clock=None):
    with open(path, encoding="utf-8") as source:
        data = json.load(source)

    if clock is None:
        clock = time.monotonic
    cache = Cache(maxsize, clock=clock)

    # A non-positive remaining TTL denotes an already expired entry. Valid
    # snapshots do not contain one, but ignoring it keeps expired entries
    # absent if such a snapshot is supplied.
    entries = [
        entry
        for entry in data["entries"]
        if entry["exp"] is None or entry["exp"] > 0
    ]

    # Snapshots are LRU first. Trim from the left before restoring so only the
    # most recently used entries survive a smaller destination cache.
    if len(entries) > maxsize:
        entries = entries[-maxsize:]

    for entry in entries:
        cache.set(entry["k"], entry["v"], ttl=entry["exp"])
    return cache
