import pytest

from intervals import merge_free_slots, min_meeting_rooms


def test_min_meeting_rooms_empty_and_zero_length():
    assert min_meeting_rooms([]) == 0
    assert min_meeting_rooms([(3, 3), (0, 0), (-2, -2)]) == 0


def test_min_meeting_rooms_overlaps_and_unsorted_input():
    meetings = [(11, 13), (9, 12), (12, 15), (10, 14), (8, 10)]
    assert min_meeting_rooms(meetings) == 3


def test_min_meeting_rooms_reuses_rooms_at_endpoints():
    assert min_meeting_rooms([(1, 3), (3, 5), (2, 3), (5, 6)]) == 2
    assert min_meeting_rooms([(0, 2), (2, 4), (4, 6)]) == 1


def test_min_meeting_rooms_rejects_reversed_interval():
    with pytest.raises(ValueError):
        min_meeting_rooms([(4, 3)])


def test_merge_free_slots_unsorted_overlapping_and_outside_day():
    busy = [
        [(14, 16), (9, 10), (10, 11), (20, 22)],
        [(12, 13), (8, 9), (13, 14), (7, 8)],
        [(11, 12), (16, 18), (-2, 7)],
    ]
    assert merge_free_slots(busy, 9, 18, 1) == []
    # The schedules above cover the whole clipped day.
    assert merge_free_slots(busy, 9, 19, 1) == [(18, 19)]


def test_merge_free_slots_combines_gaps_and_applies_minimum_length():
    busy = [
        [(10, 11), (14, 15)],
        [(9, 9), (12, 13)],
    ]
    assert merge_free_slots(busy, 9, 17, 1) == [
        (9, 10),
        (11, 12),
        (13, 14),
        (15, 17),
    ]
    assert merge_free_slots(busy, 9, 17, 2) == [(15, 17)]


def test_merge_free_slots_clips_busy_intervals_and_merges_across_people():
    busy = [
        [(-5, 2), (6, 8)],
        [(3, 4), (4, 6)],
        [(1, 3), (8, 20)],
    ]
    assert merge_free_slots(busy, 0, 10, 1) == []
    assert merge_free_slots(busy, 0, 10, 0) == []


def test_merge_free_slots_with_no_busy_time():
    assert merge_free_slots([[], []], 9, 17, 2) == [(9, 17)]
    assert merge_free_slots([], 9, 17, 9) == []
    assert merge_free_slots([[(8, 9)], [(17, 20)]], 9, 17, 8) == [(9, 17)]


def test_merge_free_slots_empty_day_and_minimum_length_boundary():
    assert merge_free_slots([[]], 5, 5, 0) == []
    assert merge_free_slots([[]], 7, 5, 0) == []
    assert merge_free_slots([[(0, 2)]], 0, 7, 5) == [(2, 7)]
    assert merge_free_slots([[(0, 2)]], 0, 7, 6) == []


def test_merge_free_slots_rejects_reversed_interval():
    with pytest.raises(ValueError):
        merge_free_slots([[(5, 4)]], 0, 10, 1)
