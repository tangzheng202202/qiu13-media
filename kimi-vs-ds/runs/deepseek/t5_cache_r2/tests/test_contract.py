import json
import os
import threading
import time

import pytest

from ttlcache import Cache
from ttlcache import persist
from ttlcache.clock import FakeClock


# ---------------------------------------------------------------- construction
@pytest.mark.parametrize("bad", [0, -1, -100])
def test_maxsize_must_be_positive(bad):
    with pytest.raises(ValueError):
        Cache(bad)


def test_default_clock_and_ttl_defaults():
    c = Cache(2)
    assert c.default_ttl is None
    c.set("a", 1)
    assert c.get("a") == 1


@pytest.mark.parametrize("bad_ttl", [0, -1, -0.5])
def test_ttl_must_be_positive(bad_ttl):
    c = Cache(2)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=bad_ttl)
    assert "a" not in c


def test_zero_ttl_does_not_fall_back_to_default():
    c = Cache(2, default_ttl=10)
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=0)


# -------------------------------------------------------------------- expiry
def test_expiry_is_inclusive():
    clk = FakeClock()
    c = Cache(2, default_ttl=5, clock=clk)
    c.set("a", 1)
    clk.advance(4.999)
    assert c.get("a") == 1
    clk.advance(0.001)  # clock() == expires_at exactly
    assert c.get("a") is None


def test_default_ttl_none_never_expires():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.set("a", 1)
    clk.advance(10 ** 9)
    assert c.get("a") == 1


def test_explicit_ttl_overrides_default():
    clk = FakeClock()
    c = Cache(2, default_ttl=100, clock=clk)
    c.set("a", 1, ttl=1)
    clk.advance(1)
    assert c.get("a") is None


def test_expired_behaves_absent_everywhere():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.set("a", 1, ttl=1)
    c.set("b", 2, ttl=100)
    assert c.get("a") == 1
    clk.advance(1)

    assert c.get("a") is None
    assert c.get("a", "d") == "d"
    assert "a" not in c
    assert "b" in c
    assert len(c) == 1
    assert c.keys() == ["b"]
    assert c.items() == [("b", 2)]
    assert c.peek("a") is None
    assert c.peek("a", "d") == "d"


def test_pop_expired_raises_or_returns_default():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.set("a", 1, ttl=1)
    clk.advance(1)
    with pytest.raises(KeyError):
        c.pop("a")
    assert c.pop("a", 7) == 7


# ------------------------------------------------------------------- recency
def test_get_marks_mru():
    c = Cache(3)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["a", "b", "c"]
    c.get("a")
    assert c.keys() == ["b", "c", "a"]


def test_set_existing_updates_and_marks_mru():
    c = Cache(3)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 10)
    assert c.keys() == ["b", "a"]
    assert c.get("a") == 10


def test_peek_does_not_touch_recency():
    c = Cache(3)
    c.set("a", 1)
    c.set("b", 2)
    c.peek("a")
    assert c.keys() == ["a", "b"]


def test_keys_items_order():
    c = Cache(4)
    for k in "abcd":
        c.set(k, k.upper())
    c.get("b")
    c.get("d")
    assert c.keys() == ["a", "c", "b", "d"]
    assert c.items() == [("a", "A"), ("c", "C"), ("b", "B"), ("d", "D")]


# ------------------------------------------------------------------ eviction
def test_evicts_lru_on_insert():
    c = Cache(2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.keys() == ["b", "c"]
    assert c.get("a") is None
    assert c.stats()["evictions"] == 1


def test_get_protects_from_eviction():
    c = Cache(2)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")
    c.set("c", 3)
    assert c.keys() == ["a", "c"]


def test_expired_entries_do_not_cause_eviction():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.set("a", 1, ttl=1)
    c.set("b", 2)
    clk.advance(1)
    c.set("c", 3)
    assert c.keys() == ["b", "c"]
    assert c.stats()["evictions"] == 0


def test_expired_entry_is_purged_before_lru_eviction():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.set("a", 1, ttl=1)   # expired soon
    c.set("b", 2)          # live
    clk.advance(1)
    # c is full of one live + one dead entry; inserting c must not evict b.
    c.set("c", 3)
    assert c.keys() == ["b", "c"]
    assert c.get("b") == 2
    assert c.stats()["evictions"] == 0


# ---------------------------------------------------------------------- pop
def test_pop_removes_and_returns():
    c = Cache(2)
    c.set("a", 1)
    assert c.pop("a") == 1
    assert "a" not in c
    with pytest.raises(KeyError):
        c.pop("a")
    assert c.pop("a", 5) == 5


def test_pop_does_not_count_as_eviction():
    c = Cache(2)
    c.set("a", 1)
    c.pop("a")
    assert c.stats()["evictions"] == 0


# -------------------------------------------------------------------- stats
def test_stats_hits_misses():
    c = Cache(2)
    assert c.stats() == {"hits": 0, "misses": 0, "evictions": 0}
    c.get("nope")
    c.set("a", 1)
    c.get("a")
    assert c.stats() == {"hits": 1, "misses": 1, "evictions": 0}


def test_stats_evictions_only_lru():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.set("a", 1, ttl=1)
    clk.advance(1)  # expiration, not eviction
    c.set("b", 2)
    c.set("c", 3)
    c.set("d", 4)  # evicts b
    assert c.stats()["evictions"] == 1


# ----------------------------------------------------------------- get_or_set
def test_get_or_set_basic():
    c = Cache(2)
    calls = []

    def factory():
        calls.append(1)
        return "v"

    assert c.get_or_set("a", factory) == "v"
    assert c.get_or_set("a", factory) == "v"
    assert len(calls) == 1
    assert c.get("a") == "v"


def test_get_or_set_uses_ttl():
    clk = FakeClock()
    c = Cache(2, clock=clk)
    c.get_or_set("a", lambda: 1, ttl=2)
    clk.advance(2)
    assert c.get("a") is None


def test_get_or_set_validates_ttl():
    c = Cache(2)
    with pytest.raises(ValueError):
        c.get_or_set("a", lambda: 1, ttl=0)


def test_get_or_set_factory_called_once_concurrently():
    c = Cache(4)
    n_threads = 16
    barrier = threading.Barrier(n_threads)
    calls = []
    lock = threading.Lock()

    def factory():
        with lock:
            calls.append(1)
        time.sleep(0.1)
        return "value"

    results = []
    errors = []

    def worker():
        try:
            barrier.wait()
            results.append(c.get_or_set("k", factory))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    assert calls == [1]
    assert results == ["value"] * n_threads


def test_slow_factory_does_not_block_other_keys():
    c = Cache(4)
    started = threading.Event()
    release = threading.Event()

    def slow_factory():
        started.set()
        release.wait(timeout=5)
        return "slow"

    t = threading.Thread(target=lambda: c.get_or_set("slow", slow_factory))
    t.start()
    assert started.wait(timeout=5)

    # While the factory runs, other keys must remain usable.
    c.set("other", 42)
    assert c.get("other") == 42
    assert c.get_or_set("other2", lambda: 7) == 7

    release.set()
    t.join(timeout=5)
    assert c.get("slow") == "slow"


# -------------------------------------------------------------- persistence
def test_save_load_roundtrip(tmp_path):
    clk = FakeClock()
    c = Cache(5, clock=clk)
    c.set("a", {"x": 1}, ttl=10)
    c.set("b", [1, 2, 3])
    c.get("a")  # LRU order becomes b, a

    path = str(tmp_path / "cache.json")
    persist.save(c, path)

    with open(path) as f:
        raw = json.load(f)
    assert list(raw.keys()) == ["entries"]
    assert [e["k"] for e in raw["entries"]] == ["b", "a"]

    new_clk = FakeClock(1000)
    loaded = persist.load(path, 5, clock=new_clk)
    assert loaded.keys() == ["b", "a"]
    assert loaded.get("a") == {"x": 1}
    assert loaded.get("b") == [1, 2, 3]

    # Remaining TTL is relative to the new clock.
    new_clk.advance(9.999)
    assert loaded.get("a") == {"x": 1}
    new_clk.advance(0.001)
    assert loaded.get("a") is None
    # Never-expiring entry survives.
    new_clk.advance(10 ** 6)
    assert loaded.get("b") == [1, 2, 3]


def test_save_skips_expired_entries(tmp_path):
    clk = FakeClock()
    c = Cache(5, clock=clk)
    c.set("live", 1)
    c.set("dead", 2, ttl=1)
    clk.advance(1)

    path = str(tmp_path / "cache.json")
    persist.save(c, path)
    with open(path) as f:
        raw = json.load(f)
    assert [e["k"] for e in raw["entries"]] == ["live"]


def test_load_keeps_most_recent_when_maxsize_smaller(tmp_path):
    c = Cache(10)
    for k in ["a", "b", "c", "d", "e"]:
        c.set(k, k)
    path = str(tmp_path / "cache.json")
    persist.save(c, path)

    loaded = persist.load(path, 2)
    # Entries are stored LRU first, so keep the most recently used (d, e).
    assert loaded.keys() == ["d", "e"]
    assert loaded.maxsize == 2


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    c = Cache(2)
    c.set("a", 1)
    path = str(tmp_path / "cache.json")
    persist.save(c, path)
    persist.save(c, path)  # overwrite

    files = os.listdir(str(tmp_path))
    assert files == ["cache.json"]
    with open(path) as f:
        assert json.load(f)["entries"][0]["k"] == "a"


def test_failed_save_keeps_original_file_and_cleans_up(tmp_path, monkeypatch):
    c = Cache(2)
    c.set("a", 1)
    path = tmp_path / "cache.json"
    path.write_text('{"entries": []}')

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(persist.json, "dump", boom)
    with pytest.raises(RuntimeError):
        persist.save(c, str(path))

    assert path.read_text() == '{"entries": []}'
    assert os.listdir(str(tmp_path)) == ["cache.json"]


def test_load_without_clock_uses_monotonic(tmp_path):
    c = Cache(2)
    c.set("a", 1, ttl=100)
    path = str(tmp_path / "cache.json")
    persist.save(c, path)
    loaded = persist.load(path, 2)
    assert loaded.get("a") == 1
