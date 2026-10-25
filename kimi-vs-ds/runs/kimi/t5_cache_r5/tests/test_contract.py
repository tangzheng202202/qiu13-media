import json
import os
import threading

import pytest

from ttlcache import Cache
from ttlcache.clock import FakeClock
from ttlcache import persist


@pytest.mark.parametrize("maxsize", [0, -1])
def test_maxsize_must_be_positive(maxsize):
    with pytest.raises(ValueError):
        Cache(maxsize)


@pytest.mark.parametrize("ttl", [0, -1])
def test_ttl_must_be_positive(ttl):
    cache = Cache(2)
    with pytest.raises(ValueError):
        cache.set("a", 1, ttl=ttl)
    assert "a" not in cache


@pytest.mark.parametrize("ttl", [0, -1])
def test_default_ttl_must_be_positive(ttl):
    with pytest.raises(ValueError):
        Cache(2, default_ttl=ttl)


def test_default_and_explicit_ttl_and_exact_expiration_boundary():
    clock = FakeClock(10)
    cache = Cache(3, default_ttl=5, clock=clock)
    cache.set("default", 1)
    cache.set("override", 2, ttl=2)

    clock.advance(2)
    assert cache.get("default") == 1
    assert cache.get("override", "missing") == "missing"

    clock.advance(3)
    assert cache.get("default", "missing") == "missing"

    no_default = Cache(1, clock=clock)
    no_default.set("forever", 3)
    clock.advance(1000)
    assert no_default.get("forever") == 3


def test_invalid_update_does_not_replace_existing_entry():
    clock = FakeClock()
    cache = Cache(1, default_ttl=5, clock=clock)
    cache.set("a", "old")
    with pytest.raises(ValueError):
        cache.set("a", "new", ttl=0)
    assert cache.peek("a") == "old"
    clock.advance(4)
    assert cache.peek("a") == "old"


def test_expired_entries_are_absent_from_all_read_operations():
    clock = FakeClock()
    cache = Cache(4, clock=clock)
    cache.set("expired", 1, ttl=2)
    cache.set("live", 2)
    clock.advance(2)

    assert cache.get("expired", "default") == "default"
    assert "expired" not in cache
    assert len(cache) == 1
    assert cache.keys() == ["live"]
    assert cache.items() == [("live", 2)]
    assert cache.peek("expired", "default") == "default"
    assert cache.pop("expired", "default") == "default"
    with pytest.raises(KeyError):
        cache.pop("expired")


def test_peek_does_not_change_recency_but_get_and_set_do():
    cache = Cache(2)
    cache.set("a", 1)
    cache.set("b", 2)

    assert cache.peek("a") == 1
    assert cache.keys() == ["a", "b"]
    assert cache.get("a") == 1
    assert cache.keys() == ["b", "a"]

    cache.set("b", 20)
    assert cache.keys() == ["a", "b"]
    assert cache.stats()["evictions"] == 0

    cache.set("c", 3)
    assert cache.items() == [("b", 20), ("c", 3)]
    assert cache.stats()["evictions"] == 1


def test_expired_entries_are_purged_before_lru_eviction():
    clock = FakeClock()
    cache = Cache(2, clock=clock)
    cache.set("expired", 1, ttl=1)
    cache.set("live", 2)
    clock.advance(1)

    cache.set("new", 3)
    assert cache.items() == [("live", 2), ("new", 3)]
    assert cache.stats()["evictions"] == 0


def test_pop_and_stats():
    clock = FakeClock()
    cache = Cache(2, clock=clock)
    assert cache.get("missing") is None
    assert cache.pop("missing", 42) == 42
    with pytest.raises(KeyError):
        cache.pop("missing")

    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.pop("a") == 1
    assert "a" not in cache

    cache.set("b", 2, ttl=1)
    clock.advance(1)
    assert cache.get("b") is None

    cache.set("c", 3)
    cache.set("d", 4)
    cache.set("e", 5)  # One genuine LRU eviction.
    assert cache.stats() == {"hits": 1, "misses": 2, "evictions": 1}


def test_get_or_set_computes_once_and_uses_default_ttl():
    clock = FakeClock()
    cache = Cache(2, default_ttl=3, clock=clock)
    calls = []

    def factory():
        calls.append(1)
        return "value"

    assert cache.get_or_set("a", factory) == "value"
    assert cache.get_or_set("a", factory) == "value"
    assert calls == [1]
    clock.advance(3)
    assert cache.get_or_set("a", factory) == "value"
    assert calls == [1, 1]


def test_get_or_set_rejects_invalid_ttl_before_calling_factory():
    cache = Cache(1)
    called = False

    def factory():
        nonlocal called
        called = True
        return 1

    with pytest.raises(ValueError):
        cache.get_or_set("a", factory, ttl=0)
    assert not called


def test_concurrent_get_or_set_calls_factory_only_once():
    cache = Cache(2)
    workers = 8
    barrier = threading.Barrier(workers)
    factory_started = threading.Event()
    release_factory = threading.Event()
    calls_lock = threading.Lock()
    calls = []
    results = []
    errors = []

    def factory():
        with calls_lock:
            calls.append(1)
        factory_started.set()
        assert release_factory.wait(5)
        return {"shared": True}

    def worker():
        try:
            barrier.wait(5)
            value = cache.get_or_set("a", factory)
            with calls_lock:
                results.append(value)
        except BaseException as exc:  # Surface thread failures in the test.
            with calls_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    assert factory_started.wait(5)
    release_factory.set()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()

    assert not errors
    assert calls == [1]
    assert results == [{"shared": True}] * workers


def test_slow_factory_does_not_block_other_keys():
    cache = Cache(3)
    factory_started = threading.Event()
    release_factory = threading.Event()
    other_operation_done = threading.Event()
    errors = []

    def slow_factory():
        factory_started.set()
        assert release_factory.wait(5)
        return "a"

    first = threading.Thread(target=lambda: cache.get_or_set("a", slow_factory))
    first.start()
    assert factory_started.wait(5)

    def operate_on_other_key():
        try:
            cache.set("b", "b")
            assert cache.get("b") == "b"
            assert cache.peek("b") == "b"
            assert cache.keys() == ["b"]
        except BaseException as exc:
            errors.append(exc)
        finally:
            other_operation_done.set()

    other = threading.Thread(target=operate_on_other_key)
    other.start()
    assert other_operation_done.wait(2), "an unrelated key was blocked by factory()"
    release_factory.set()
    first.join(5)
    other.join(5)
    assert not first.is_alive()
    assert not other.is_alive()
    assert not errors
    assert cache.get("a") == "a"


def test_different_keys_can_run_factories_concurrently():
    cache = Cache(2)
    first_started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()

    def first_factory():
        first_started.set()
        assert release.wait(5)
        return 1

    def second_factory():
        second_started.set()
        assert release.wait(5)
        return 2

    first = threading.Thread(target=lambda: cache.get_or_set("a", first_factory))
    second = threading.Thread(target=lambda: cache.get_or_set("b", second_factory))
    first.start()
    assert first_started.wait(5)
    second.start()
    assert second_started.wait(2), "factories for different keys were serialized"
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive()
    assert not second.is_alive()
    assert cache.items() == [("a", 1), ("b", 2)]


def test_save_stores_live_entries_remaining_ttls_and_lru_order(tmp_path):
    clock = FakeClock(10)
    cache = Cache(3, clock=clock)
    cache.set("a", {"number": 1}, ttl=10)
    cache.set("b", [1, 2])
    cache.set("expired", True, ttl=2)
    cache.get("a")  # LRU order is now b, expired, a.
    clock.advance(2)

    path = tmp_path / "snapshot.json"
    persist.save(cache, path)
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)

    assert data == {
        "entries": [
            {"k": "b", "v": [1, 2], "exp": None},
            {"k": "a", "v": {"number": 1}, "exp": 8},
        ]
    }


def test_save_uses_atomic_same_directory_replace(tmp_path, monkeypatch):
    cache = Cache(1)
    cache.set("a", 1)
    path = tmp_path / "snapshot.json"
    path.write_text("old snapshot", encoding="utf-8")
    calls = []
    real_replace = persist.os.replace

    def checked_replace(source, target):
        calls.append((source, target))
        assert os.path.dirname(source) == str(tmp_path)
        assert os.path.exists(source)
        assert os.path.abspath(target) == str(path)
        real_replace(source, target)

    monkeypatch.setattr(persist.os, "replace", checked_replace)
    persist.save(cache, path)

    assert len(calls) == 1
    assert calls[0][0] != str(path)
    assert json.loads(path.read_text(encoding="utf-8"))["entries"][0]["k"] == "a"
    assert list(tmp_path.iterdir()) == [path]


def test_load_restores_order_and_remaining_ttls_on_new_clock(tmp_path):
    old_clock = FakeClock(50)
    cache = Cache(3, clock=old_clock)
    cache.set("a", 1, ttl=5)
    cache.set("b", 2, ttl=10)
    cache.set("c", 3)
    cache.get("a")  # b, c, a
    old_clock.advance(2)
    path = tmp_path / "snapshot.json"
    persist.save(cache, path)

    new_clock = FakeClock(1000)
    loaded = persist.load(path, 3, clock=new_clock)
    assert loaded.items() == [("b", 2), ("c", 3), ("a", 1)]

    new_clock.advance(3)
    assert "a" not in loaded
    assert loaded.keys() == ["b", "c"]
    new_clock.advance(5)
    assert "b" not in loaded
    new_clock.advance(1000)
    assert loaded.items() == [("c", 3)]


def test_load_with_smaller_maxsize_keeps_mru_tail(tmp_path):
    cache = Cache(4)
    for key in "abcd":
        cache.set(key, key)
    path = tmp_path / "snapshot.json"
    persist.save(cache, path)

    loaded = persist.load(path, 2)
    assert loaded.items() == [("c", "c"), ("d", "d")]
