import sys, os, json, threading, time; sys.path.insert(0, os.path.dirname(__file__))
import pytest
from ttlcache import Cache
from ttlcache import persist
from ttlcache.clock import FakeClock
def test_lru_evicts_oldest():
    c = Cache(2); c.set("a",1); c.set("b",2); c.set("c",3); assert c.get("a") is None and c.get("b")==2
def test_get_updates_recency():
    c = Cache(2); c.set("a",1); c.set("b",2); c.get("a"); c.set("c",3); assert c.get("a")==1 and c.get("b") is None
def test_peek_no_recency():
    c = Cache(2); c.set("a",1); c.set("b",2); assert c.peek("a")==1; c.set("c",3); assert c.peek("a") is None
def test_set_existing_mru():
    c = Cache(2); c.set("a",1); c.set("b",2); c.set("a",9); c.set("c",3); assert c.get("a")==9 and "b" not in c
def test_expiry_boundary():
    k=FakeClock(); c=Cache(5,clock=k); c.set("a",1,ttl=10); k.advance(10); assert c.get("a") is None
def test_expired_absent_everywhere():
    k=FakeClock(); c=Cache(5,clock=k); c.set("a",1,ttl=1); c.set("b",2); k.advance(2)
    assert "a" not in c and len(c)==1 and c.keys()==["b"] and c.items()==[("b",2)]
def test_expired_not_counted_for_eviction():
    k=FakeClock(); c=Cache(2,clock=k); c.set("a",1,ttl=1); c.set("b",2); k.advance(5); c.set("c",3)
    assert c.get("b")==2 and c.get("c")==3 and c.stats()["evictions"]==0
def test_ttl_zero_invalid():
    c=Cache(2,default_ttl=5)
    with pytest.raises(ValueError): c.set("a",1,ttl=0)
    with pytest.raises(ValueError): c.set("a",1,ttl=-1)
def test_maxsize_invalid():
    with pytest.raises(ValueError): Cache(0)
def test_default_ttl():
    k=FakeClock(); c=Cache(2,default_ttl=3,clock=k); c.set("a",1); k.advance(3); assert c.get("a") is None
def test_pop():
    k=FakeClock(); c=Cache(2,clock=k); c.set("a",1,ttl=1); k.advance(1)
    with pytest.raises(KeyError): c.pop("a")
    assert c.pop("a",7)==7
def test_stats():
    c=Cache(1); c.set("a",1); c.get("a"); c.get("z"); c.set("b",2); assert c.stats()=={"hits":1,"misses":1,"evictions":1}
def test_get_or_set_once_concurrent():
    calls=[]; c=Cache(10)
    def fac(): calls.append(1); time.sleep(0.05); return 42
    ts=[threading.Thread(target=lambda: c.get_or_set("k",fac)) for _ in range(16)]
    [t.start() for t in ts]; [t.join() for t in ts]; assert len(calls)==1 and c.get("k")==42
def test_get_or_set_other_keys_not_blocked():
    c=Cache(10); ev=threading.Event()
    def slow(): ev.wait(2); return 1
    t=threading.Thread(target=lambda: c.get_or_set("slow",slow)); t.start(); time.sleep(0.05)
    t0=time.time(); c.set("x",1); assert c.get("x")==1; ok=time.time()-t0<0.5; ev.set(); t.join(); assert ok
def test_thread_safety_hammer():
    c=Cache(50); errs=[]
    def w(i):
        try:
            for j in range(2000):
                c.set(f"{(i*j)%120}", j); c.get(f"{j%120}"); c.peek(f"{j%77}"); len(c); c.keys()
        except Exception as e: errs.append(e)
    ts=[threading.Thread(target=w,args=(i,)) for i in range(8)]; [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs and len(c)<=50
def test_persist_roundtrip_order_and_ttl(tmp_path):
    k=FakeClock(100); c=Cache(3,clock=k); c.set("a",1,ttl=10); c.set("b",[1,2]); c.set("c","x",ttl=50); c.get("a")
    k.advance(4); p=tmp_path/"s.json"; persist.save(c,str(p))
    k2=FakeClock(0); d=persist.load(str(p),3,clock=k2)
    assert d.keys()==["b","c","a"]
    k2.advance(5.9); assert d.get("a")==1; k2.advance(0.2); assert d.get("a") is None and d.get("b")==[1,2]
def test_persist_skips_expired(tmp_path):
    k=FakeClock(); c=Cache(3,clock=k); c.set("a",1,ttl=1); c.set("b",2); k.advance(2); p=tmp_path/"s.json"; persist.save(c,str(p))
    assert [e for e in json.load(open(p))["entries"]] and len(json.load(open(p))["entries"])==1
def test_persist_atomic(tmp_path, monkeypatch):
    c=Cache(3); c.set("a",1); p=tmp_path/"s.json"; persist.save(c,str(p))
    import os as _os; called={}
    real=_os.replace
    def fake(a,b): called["x"]=(a,b); return real(a,b)
    monkeypatch.setattr(persist.os,"replace",fake); c.set("b",2); persist.save(c,str(p))
    assert called and os.path.dirname(os.path.abspath(called["x"][0]))==str(tmp_path) and len(json.load(open(p))["entries"])==2
def test_persist_load_smaller_maxsize(tmp_path):
    c=Cache(3); c.set("a",1); c.set("b",2); c.set("c",3); c.get("a"); p=tmp_path/"s.json"; persist.save(c,str(p))
    d=persist.load(str(p),2); assert d.keys()==["c","a"]
