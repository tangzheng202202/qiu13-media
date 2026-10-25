import pytest
from ratelimit import TokenBucket, KeyedLimiter
class C:
    def __init__(s): s.t=0.0
    def __call__(s): return s.t
def test_basic():
    c=C(); b=TokenBucket(3,1.0,clock=c)
    assert [b.allow() for _ in range(4)]==[True,True,True,False]
    c.t=1.0; assert b.allow() and not b.allow()
def test_cap():
    c=C(); b=TokenBucket(2,10,clock=c); c.t=100; assert b.allow(2) and not b.allow()
def test_no_partial():
    c=C(); b=TokenBucket(3,1,clock=c); b.allow(2); assert not b.allow(2); c.t=1; assert b.allow(2)
def test_errors():
    b=TokenBucket(2,1,clock=C())
    for x in (0,-1,3):
        with pytest.raises(ValueError): b.allow(x)
def test_wait():
    c=C(); b=TokenBucket(2,0.5,clock=c); assert b.wait_time()==0.0; b.allow(2)
    assert b.wait_time(1)==pytest.approx(2.0); c.t=1; assert b.wait_time(2)==pytest.approx(3.0)
def test_keyed_lru():
    c=C(); k=KeyedLimiter(1,0.001,clock=c,max_keys=2)
    assert k.allow("a") and k.allow("b"); k.allow("a")  # touch a
    assert k.allow("c"); assert len(k)==2
    assert not k.allow("a")  # a retained (used)
    assert k.allow("b")  # b evicted -> fresh bucket
