import pytest, random
from intervals import min_meeting_rooms, merge_free_slots
def test_rooms():
    assert min_meeting_rooms([])==0
    assert min_meeting_rooms([(0,30),(5,10),(15,20)])==2
    assert min_meeting_rooms([(1,5),(5,10)])==1
    assert min_meeting_rooms([(3,3),(3,3)])==0
    assert min_meeting_rooms([(1,10),(2,3),(3,3),(2,10)])==3
    with pytest.raises(ValueError): min_meeting_rooms([(5,1)])
def test_rooms_random():
    random.seed(1)
    for _ in range(200):
        m=[(a,a+random.randint(0,5)) for a in [random.randint(0,20) for _ in range(8)]]
        brute=max([sum(1 for s,e in m if s<=t<e) for t in range(30)]+[0])
        assert min_meeting_rooms(m)==brute
def test_free():
    busy=[[(9,10),(12,13)],[(9,11),(15,20)]]
    assert merge_free_slots(busy,8,17,1)==[(8,9),(11,12),(13,15)]
    assert merge_free_slots(busy,8,17,2)==[(13,15)]
    assert merge_free_slots([[(0,24)]],8,17,1)==[]
    assert merge_free_slots([],8,17,1)==[(8,17)]
    assert merge_free_slots([[(10,12),(11,13)],[]],9,14,1)==[(9,10),(13,14)]
