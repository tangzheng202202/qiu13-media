"""Utilities for meeting rooms and common calendar availability."""


def min_meeting_rooms(meetings: list[tuple[int, int]]) -> int:
    """Return the minimum number of rooms needed for ``meetings``.

    Meetings are half-open intervals, so an ending meeting releases its room
    before another meeting starts at the same time.  Zero-length meetings do
    not occupy a room.
    """
    events: list[tuple[int, int]] = []
    for start, end in meetings:
        if start > end:
            raise ValueError("meeting start must not be after its end")
        if start == end:
            continue
        # Ends sort before starts at equal times because -1 < 1.
        events.append((start, 1))
        events.append((end, -1))

    events.sort()
    occupied = 0
    max_occupied = 0
    for _, change in events:
        occupied += change
        if occupied > max_occupied:
            max_occupied = occupied
    return max_occupied


def merge_free_slots(
    busy: list[list[tuple[int, int]]],
    day_start: int,
    day_end: int,
    min_len: int,
) -> list[tuple[int, int]]:
    """Return common free slots within the half-open day interval.

    A time is commonly free precisely when it occurs in no person's busy
    interval.  Thus all clipped busy intervals can be unioned, and the gaps
    in that union are the desired slots.  Only positive-length busy intervals
    and free slots are considered.
    """
    if day_end <= day_start:
        return []

    clipped: list[tuple[int, int]] = []
    for schedule in busy:
        for start, end in schedule:
            if start > end:
                raise ValueError("busy interval start must not be after its end")
            start = max(start, day_start)
            end = min(end, day_end)
            if start < end:
                clipped.append((start, end))

    clipped.sort()
    free: list[tuple[int, int]] = []
    cursor = day_start

    for start, end in clipped:
        if start > cursor:
            if start - cursor >= min_len:
                free.append((cursor, start))
            cursor = end
        elif end > cursor:
            cursor = end

    if cursor < day_end and day_end - cursor >= min_len:
        free.append((cursor, day_end))

    return free
