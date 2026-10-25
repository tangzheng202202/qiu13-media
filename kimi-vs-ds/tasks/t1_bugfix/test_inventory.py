from datetime import date
import pytest
from inventory import Inventory
T = date(2026,1,10)
def mk():
    i = Inventory()
    i.add("a", 5, date(2026,1,20)); i.add("a", 5, date(2026,1,12)); i.add("a", 3, date(2026,1,5))
    return i
def test_total(): assert mk().total("a", T) == 10
def test_fefo():
    i = mk(); i.remove("a", 6, T)
    assert sorted(i.items["a"], key=lambda x:x[1]) == [(4, date(2026,1,20))] or sorted([l for l in i.items["a"] if l[0]>0], key=lambda x:x[1]) == [(4, date(2026,1,20))]
def test_no_zero_lots():
    i = mk(); i.remove("a", 5, T)
    assert all(q > 0 for q, _ in i.items["a"])
def test_expired_kept_out_of_total():
    i = mk(); i.remove("a", 1, T); assert i.total("a", T) == 9
def test_insufficient():
    with pytest.raises(ValueError): mk().remove("a", 11, T)
def test_expiring_inclusive():
    i = mk(); r = i.expiring_within(T, 2)
    assert r == [("a", 5, date(2026,1,12))]
def test_expiring_today_included():
    i = Inventory(); i.add("b", 1, T); assert i.expiring_within(T, 1) == [("b", 1, T)]
