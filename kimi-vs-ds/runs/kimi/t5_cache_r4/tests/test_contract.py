import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ttlcache import Cache
from ttlcache import persist
from ttlcache.clock import FakeClock


def test_constructor_and_ttl_validation():
    with pytest.raises(ValueError):
        Cache(0)
    with pytest.raises(ValueError):
        Cache(-1)
    with pytest.raises(ValueError):
        Cache(1, default_ttl=0)

    cache = Cache(2, default_ttl=5)
    with pytest.raises(ValueError):
        cache.set("zero", 1, ttl=0)
    with pytest.raises(ValueError):
        cache.set("negative", 1, ttl=-1)
    assert cache.keys() == []


def test_default_ttl_and_expiration_boundary():
    clock = FakeClock()
    cache = Cache(4, default_ttl=5, clock=clock)
    cache.set("default", 1)
    cache.set("override", 2, ttl=2)
    cache.set("also-default", 3, ttl=None)  # None selects the default TTL.
    cache.set("long-lived", 4, ttl=10)

    clock.advance(2)
    assert cache.get("default") == 1
    assert cache.get("override", "missing") == "missing"
    clock.advance(3)
    assert cache.get("default", "missing") == "missing"
    assert "also-default" not in cache
    assert cache.get("long-lived") == 4


def test_expired_entries_are_absent_and_do_not_evict_live_entries():
    clock = FakeClock()
    cache = Cache(2, clock=clock)
    cache.set("old", 1, ttl=2)
    cache.set("live", 2)
    clock.advance(2)

    assert cache.get("old", "missing") == "missing"
    assert "old" not in cache
    assert len(cache) == 1
    assert cache.keys() == ["live"]
    assert cache.items() == [("live", 2)]
    assert cache.pop("old", "missing") == "missing"
    with pytest.raises(KeyError):
        cache.pop("old")

    cache.set("old", 3, ttl=2)
    clock.advance(2)
    cache.set("new", 4)
    assert cache.keys() == ["live", "new"]
    assert cache.stats()["evictions"] == 0


def test_lru_recency_and_peek():
    cache = Cache(2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.peek("a") == 1
    assert cache.keys() == ["a", "b"]

    assert cache.get("a") == 1
    assert cache.keys() == ["b", "a"]
    cache.set("b", 20)
    assert cache.keys() == ["a", "b"]
    cache.set("c", 3)
    assert cache.keys() == ["b", "c"]
    assert cache.get("a") is None
    assert cache.stats() == {"hits": 1, "misses": 1, "evictions": 1}


def test_pop_and_stats_do_not_count_expiration_as_eviction():
    cache = Cache(2)
    cache.set("a", None)
    assert cache.pop("a") is None
    assert cache.pop("a", 42) == 42
    with pytest.raises(KeyError):
        cache.pop("a")
    assert cache.stats() == {"hits": 0, "misses": 0, "evictions": 0}


def test_get_or_set_calls_factory_once_for_a_live_key():
    cache = Cache(4)
    calls = 0
    calls_lock = threading.Lock()

    def factory():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.02)
        return "computed"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.get_or_set("key", factory), range(16)))

    assert results == ["computed"] * 16
    assert calls == 1
    assert cache.get("key") == "computed"


def test_slow_factory_does_not_block_other_keys():
    cache = Cache(4)
    started = threading.Event()
    release = threading.Event()

    def slow_factory():
        started.set()
        assert release.wait(2)
        return "slow"

    with ThreadPoolExecutor(max_workers=2) as pool:
        slow_result = pool.submit(cache.get_or_set, "slow", slow_factory)
        assert started.wait(1)
        try:
            other_result = pool.submit(cache.get_or_set, "other", lambda: "fast")
            assert other_result.result(timeout=1) == "fast"
            assert cache.get("other") == "fast"
        finally:
            release.set()
        assert slow_result.result(timeout=1) == "slow"


def test_save_uses_remaining_ttls_order_and_atomic_replace(tmp_path, monkeypatch):
    clock = FakeClock(10)
    cache = Cache(4, clock=clock)
    cache.set("a", {"value": 1}, ttl=20)
    cache.set("b", [1, 2])
    cache.set("expired", "not saved", ttl=5)
    clock.advance(5)
    assert cache.get("a") == {"value": 1}  # b, a in LRU -> MRU order

    path = tmp_path / "snapshot.json"
    replacements = []
    real_replace = persist.os.replace

    def checked_replace(source, destination):
        replacements.append((source, destination))
        assert os.path.dirname(source) == str(tmp_path)
        assert os.path.exists(source)
        return real_replace(source, destination)

    monkeypatch.setattr(persist.os, "replace", checked_replace)
    persist.save(cache, path)

    assert len(replacements) == 1
    assert json.loads(path.read_text()) == {
        "entries": [
            {"k": "b", "v": [1, 2], "exp": None},
            {"k": "a", "v": {"value": 1}, "exp": 15},
        ]
    }
    assert list(tmp_path.iterdir()) == [path]


def test_load_restores_order_relative_ttls_and_mru_capacity(tmp_path):
    source_clock = FakeClock(50)
    source = Cache(4, clock=source_clock)
    source.set("a", 1, ttl=10)
    source.set("b", 2)
    source.set("c", 3, ttl=20)
    source.get("a")  # b, c, a
    path = tmp_path / "snapshot.json"
    persist.save(source, path)

    new_clock = FakeClock(1000)
    restored = persist.load(path, 3, clock=new_clock)
    assert restored.keys() == ["b", "c", "a"]
    new_clock.advance(10)
    assert "a" not in restored
    assert restored.get("c") == 3

    smaller = persist.load(path, 2, clock=FakeClock(2000))
    assert smaller.keys() == ["c", "a"]
