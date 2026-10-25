import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ttlcache import Cache
from ttlcache.clock import FakeClock
def test_set_get():
    c = Cache(2); c.set("a", 1); assert c.get("a") == 1
def test_missing():
    assert Cache(2).get("x", 5) == 5
