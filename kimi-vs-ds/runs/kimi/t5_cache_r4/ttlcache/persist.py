"""Atomic JSON snapshot persistence for :mod:`ttlcache`."""

import json
import os
import tempfile

from .cache import Cache


def save(cache, path):
    """Atomically save the live entries in *cache* to *path*.

    The cache snapshot is taken before any file I/O.  In particular, the
    monotonic expiration timestamps never appear in the JSON file: only the
    TTL remaining at the snapshot is stored.
    """
    entries = [
        {"k": key, "v": value, "exp": remaining}
        for key, value, remaining in cache._remaining()
    ]

    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    prefix = b".ttlcache-" if isinstance(path, bytes) else ".ttlcache-"
    fd, temp_path = tempfile.mkstemp(prefix=prefix, dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"entries": entries}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        # A failed dump or replace must not leave a partial snapshot or temp
        # file behind.  If replace succeeded, the temporary name no longer
        # exists and cleanup is simply a no-op.
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load(path, maxsize, clock=None):
    """Load a snapshot, retaining LRU order and at most *maxsize* entries."""
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)

    cache = Cache(maxsize, clock=clock) if clock is not None else Cache(maxsize)

    # Snapshots written by save contain live entries only.  Also discard an
    # entry whose remaining TTL is non-positive when reading a snapshot from
    # another source: it is already expired and must not consume capacity or
    # be passed to Cache.set (which quite correctly rejects such a TTL).
    entries = []
    for entry in data["entries"]:
        remaining = entry["exp"]
        if remaining is not None and remaining <= 0:
            continue
        entries.append(entry)

    # Entries are serialized LRU first.  Dropping from the LRU end both
    # enforces a smaller load-time capacity and avoids counting restoration
    # as ordinary LRU evictions.
    while len(entries) > maxsize:
        entries.pop(0)

    # Inserting in the original order appends each successive entry at the
    # MRU end, reproducing the saved order exactly.
    for entry in entries:
        cache.set(entry["k"], entry["v"], ttl=entry["exp"])
    return cache
