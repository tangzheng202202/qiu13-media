import pytest

from intervals import merge_free_slots, min_meeting_rooms


# ---------------------------------------------------------------------------
# min_meeting_rooms
# ---------------------------------------------------------------------------


def test_min_meeting_rooms_empty():
    assert min_meeting_rooms([]) == 0


def test_min_meeting_rooms_single():
    assert min_meeting_rooms([(1, 5)]) == 1


def test_min_meeting_rooms_disjoint():
    assert min_meeting_rooms([(0, 1), (2, 3), (4, 5)]) == 1


def test_min_meeting_rooms_touching_intervals():
    # [0, 1) and [1, 2) can share a room.
    assert min_meeting_rooms([(0, 1), (1, 2)]) == 1


def test_min_meeting_rooms_overlapping():
    assert min_meeting_rooms([(0, 30), (5, 10), (15, 20)]) == 2


def test_min_meeting_rooms_three_way_overlap():
    assert min_meeting_rooms([(0, 10), (1, 11), (2, 12)]) == 3


def test_min_meeting_rooms_nested():
    assert min_meeting_rooms([(0, 100), (10, 20), (30, 40)]) == 2
    assert min_meeting_rooms([(0, 100), (0, 50), (0, 25)]) == 3


def test_min_meeting_rooms_zero_length_needs_no_room():
    assert min_meeting_rooms([(5, 5)]) == 0
    assert min_meeting_rooms([(0, 10), (5, 5), (10, 10)]) == 1


def test_min_meeting_rooms_zero_length_inside_busy_period():
    assert min_meeting_rooms([(1, 4), (2, 2), (3, 3)]) == 1


def test_min_meeting_rooms_unsorted():
    assert min_meeting_rooms([(15, 20), (0, 30), (5, 10)]) == 2


def test_min_meeting_rooms_same_start_and_end():
    assert min_meeting_rooms([(0, 5), (0, 5), (0, 5)]) == 3


def test_min_meeting_rooms_reuse_at_boundaries():
    assert min_meeting_rooms([(0, 2), (1, 3), (2, 4), (3, 5)]) == 2


def test_min_meeting_rooms_negative_times():
    assert min_meeting_rooms([(-10, -5), (-7, -2)]) == 2


@pytest.mark.parametrize("interval", [(5, 4), (0, -1), (3, 1)])
def test_min_meeting_rooms_invalid(interval):
    with pytest.raises(ValueError):
        min_meeting_rooms([interval])


def test_min_meeting_rooms_invalid_even_with_zero_length_present():
    with pytest.raises(ValueError):
        min_meeting_rooms([(0, 0), (5, 3)])


# ---------------------------------------------------------------------------
# merge_free_slots
# ---------------------------------------------------------------------------


def test_merge_free_slots_no_busy():
    assert merge_free_slots([], 0, 10, 1) == [(0, 10)]


def test_merge_free_slots_empty_people_lists():
    assert merge_free_slots([[], []], 0, 10, 1) == [(0, 10)]


def test_merge_free_slots_basic():
    busy = [[(1, 3), (5, 7)], [(2, 4), (6, 8)]]
    assert merge_free_slots(busy, 0, 10, 1) == [(0, 1), (4, 5), (8, 10)]


def test_merge_free_slots_overlapping_within_person():
    busy = [[(1, 5), (3, 6)]]
    assert merge_free_slots(busy, 0, 10, 1) == [(0, 1), (6, 10)]


def test_merge_free_slots_unsorted():
    busy = [[(6, 8), (1, 3)], [(5, 7), (2, 4)]]
    assert merge_free_slots(busy, 0, 10, 1) == [(0, 1), (4, 5), (8, 10)]


def test_merge_free_slots_clips_to_day():
    busy = [[(-5, 2), (8, 20)]]
    assert merge_free_slots(busy, 0, 10, 1) == [(2, 8)]


def test_merge_free_slots_busy_entirely_outside_day():
    busy = [[(-10, -5), (20, 30)]]
    assert merge_free_slots(busy, 0, 10, 1) == [(0, 10)]


def test_merge_free_slots_busy_covers_day():
    busy = [[(0, 5), (5, 10)]]
    assert merge_free_slots(busy, 0, 10, 1) == []


def test_merge_free_slots_busy_touching_day_boundaries():
    busy = [[(-5, 0), (10, 15)]]
    assert merge_free_slots(busy, 0, 10, 1) == [(0, 10)]


def test_merge_free_slots_min_len_filtering():
    busy = [[(1, 2), (3, 5), (6, 10)]]
    # Gaps are [0, 1), [2, 3), [5, 6); day ends at 10.
    assert merge_free_slots(busy, 0, 10, 1) == [(0, 1), (2, 3), (5, 6)]
    assert merge_free_slots(busy, 0, 10, 2) == []


def test_merge_free_slots_min_len_exact_boundary():
    busy = [[(0, 2), (4, 10)]]
    assert merge_free_slots(busy, 0, 10, 2) == [(2, 4)]
    assert merge_free_slots(busy, 0, 10, 3) == []


def test_merge_free_slots_min_len_zero():
    busy = [[(0, 5), (5, 10)]]
    assert merge_free_slots(busy, 0, 10, 0) == []


def test_merge_free_slots_day_start_equals_day_end():
    assert merge_free_slots([[(0, 10)]], 5, 5, 1) == []
    assert merge_free_slots([], 5, 5, 0) == []


def test_merge_free_slots_day_start_after_day_end():
    assert merge_free_slots([], 10, 5, 1) == []


def test_merge_free_slots_all_busy_for_every_person():
    busy = [[(0, 10)], [(0, 10)]]
    assert merge_free_slots(busy, 0, 10, 1) == []


def test_merge_free_slots_min_len_larger_than_day():
    assert merge_free_slots([], 0, 5, 6) == []


def test_merge_free_slots_adjacent_gaps_are_separate():
    busy = [[(1, 2), (3, 4)]]
    assert merge_free_slots(busy, 0, 5, 1) == [(0, 1), (2, 3), (4, 5)]


def test_merge_free_slots_duplicate_intervals():
    busy = [[(1, 3)], [(1, 3)], [(1, 3)]]
    assert merge_free_slots(busy, 0, 5, 1) == [(0, 1), (3, 5)]
