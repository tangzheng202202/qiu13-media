import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ttlcache import Cache, persist
from ttlcache.clock import FakeClock


def test_constructor_and_ttl_validation():
    for maxsize in (0, -1):
        with pytest.raises(ValueError):
            Cache(maxsize)

    cache = Cache(2, default_ttl=5)
    for ttl in (0, -1):
        with pytest.raises(ValueError):
            cache.set("a", 1, ttl=ttl)

    with pytest.raises(ValueError):
        Cache(1, default_ttl=0)


def test_lru_recency_for_get_set_and_peek():
    cache = Cache(2)
    cache.set("a", 1)
    cache.set("b", 2)

    assert cache.peek("a") == 1
    cache.set("c", 3)
    assert "a" not in cache  # peek did not make it MRU
    assert cache.keys() == ["b", "c"]

    assert cache.get("b") == 2
    cache.set("c", 30)  # updating an existing key also makes it MRU
    assert cache.keys() == ["b", "c"]
    cache.set("d", 4)
    assert cache.keys() == ["c", "d"]
    assert cache.stats()["evictions"] == 2


def test_expiry_boundary_and_absent_behavior():
    clock = FakeClock()
    cache = Cache(4, clock=clock)
    cache.set("a", 1, ttl=2)
    cache.set("b", 2)
    clock.advance(2)

    assert cache.get("a") is None
    assert "a" not in cache
    assert cache.peek("a", "missing") == "missing"
    assert cache.pop("a", "missing") == "missing"
    with pytest.raises(KeyError):
        cache.pop("a")
    assert len(cache) == 1
    assert cache.keys() == ["b"]
    assert cache.items() == [("b", 2)]


def test_default_ttl_and_updating_ttl():
    clock = FakeClock()
    cache = Cache(2, default_ttl=3, clock=clock)
    cache.set("a", 1)
    clock.advance(2)
    cache.set("a", 2, ttl=5)
    clock.advance(4)
    assert cache.get("a") == 2
    clock.advance(1)
    assert cache.get("a") is None


def test_expired_entries_are_purged_before_eviction():
    clock = FakeClock()
    cache = Cache(2, clock=clock)
    cache.set("a", 1, ttl=1)
    cache.set("b", 2)
    clock.advance(1)
    cache.set("c", 3)

    assert cache.keys() == ["b", "c"]
    assert cache.stats()["evictions"] == 0


def test_pop_and_stats():
    cache = Cache(1)
    assert cache.get("missing") is None
    cache.set("a", 1)
    assert cache.get("a") == 1
    cache.set("b", 2)

    assert cache.stats() == {"hits": 1, "misses": 1, "evictions": 1}
    assert cache.pop("b") == 2
    assert cache.pop("b", 7) == 7
    with pytest.raises(KeyError):
        cache.pop("b")


def test_get_or_set_runs_one_factory_for_a_live_key():
    cache = Cache(2)
    thread_count = 8
    barrier = threading.Barrier(thread_count)
    calls = 0
    calls_lock = threading.Lock()
    results = []
    results_lock = threading.Lock()

    def factory():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.02)
        return 42

    def worker():
        barrier.wait()
        value = cache.get_or_set("key", factory)
        with results_lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert results == [42] * thread_count
    assert calls == 1


def test_slow_factory_does_not_block_other_keys():
    cache = Cache(3)
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def slow_factory():
        entered.set()
        assert release.wait(timeout=2)
        return "slow"

    def worker():
        try:
            cache.get_or_set("slow", slow_factory)
        except Exception as exc:  # pragma: no cover - reported by assertion
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=1)
    try:
        cache.set("other", 2)
        assert cache.get("other") == 2
        assert cache.get_or_set("fast", lambda: 3) == 3
    finally:
        release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert not errors


def test_persistence_round_trip_preserves_order_and_remaining_ttl(tmp_path):
    clock = FakeClock(100)
    cache = Cache(3, clock=clock)
    cache.set("a", 1, ttl=10)
    cache.set("b", 2)
    cache.set("c", 3, ttl=50)
    clock.advance(4)
    assert cache.get("a") == 1  # order is now b, c, a

    path = tmp_path / "snapshot.json"
    persist.save(cache, path)
    with path.open() as source:
        saved = json.load(source)
    assert [entry["k"] for entry in saved["entries"]] == ["b", "c", "a"]
    assert [entry["exp"] for entry in saved["entries"]] == [None, 46, 6]

    restored = persist.load(path, 3, clock=clock)
    assert restored.keys() == ["b", "c", "a"]
    clock.advance(5.9)
    assert restored.get("a") == 1
    clock.advance(0.2)
    assert restored.get("a") is None
    assert restored.get("b") == 2


def test_persistence_skips_expired_and_trims_lru_entries(tmp_path):
    clock = FakeClock()
    cache = Cache(3, clock=clock)
    cache.set("a", 1, ttl=1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("b") == 2  # order is c, b while a is live
    clock.advance(1)

    path = tmp_path / "snapshot.json"
    persist.save(cache, path)
    with path.open() as source:
        assert [entry["k"] for entry in json.load(source)["entries"]] == ["c", "b"]

    restored = persist.load(path, 1, clock=clock)
    assert restored.keys() == ["b"]


def test_persistence_uses_atomic_replace_in_destination_directory(
    tmp_path, monkeypatch
):
    cache = Cache(1)
    cache.set("a", 1)
    path = tmp_path / "snapshot.json"
    real_replace = os.replace
    replaced = []

    def checking_replace(source, destination):
        replaced.append((source, destination))
        assert os.path.dirname(os.path.abspath(source)) == str(tmp_path)
        assert os.path.abspath(destination) == str(path)
        real_replace(source, destination)

    monkeypatch.setattr(persist.os, "replace", checking_replace)
    persist.save(cache, path)

    assert len(replaced) == 1
    assert persist.load(path, 1).items() == [("a", 1)]
