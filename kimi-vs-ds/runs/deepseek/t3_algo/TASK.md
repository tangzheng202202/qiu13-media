# Task: `intervals.py`
Implement `min_meeting_rooms(meetings: list[tuple[int,int]]) -> int` (half-open intervals [start,end); a meeting ending at t frees the room for one starting at t; zero-length meetings (start==end) need no room; raise ValueError if start>end),
and `merge_free_slots(busy: list[list[tuple[int,int]]], day_start: int, day_end: int, min_len: int) -> list[tuple[int,int]]` returning common free slots of all people within [day_start, day_end), each of length >= min_len, sorted. Busy intervals may overlap, be unsorted, or extend outside the day.
Must be O(n log n). Write tests in `test_intervals.py`.
