"""Utilities for working with half-open integer intervals ``[start, end)``."""

from __future__ import annotations


def min_meeting_rooms(meetings: list[tuple[int, int]]) -> int:
    """Return the minimum number of rooms needed for ``meetings``.

    Intervals are half-open: a meeting ending at ``t`` frees its room for a
    meeting starting at ``t``.  Zero-length meetings (``start == end``) need no
    room and therefore never affect the result.

    Raises:
        ValueError: If any meeting has ``start > end``.
    """
    events: list[tuple[int, int]] = []
    for start, end in meetings:
        if start > end:
            raise ValueError(
                f"invalid meeting interval: start ({start}) > end ({end})"
            )
        if start == end:
            # A zero-length meeting requires no room.
            continue
        # Process end events before start events at the same timestamp so that
        # a room is reused when one meeting ends exactly when another begins.
        events.append((start, 1))
        events.append((end, -1))

    events.sort()

    current = 0
    max_rooms = 0
    for _, delta in events:
        current += delta
        if current > max_rooms:
            max_rooms = current
    return max_rooms


def merge_free_slots(
    busy: list[list[tuple[int, int]]],
    day_start: int,
    day_end: int,
    min_len: int,
) -> list[tuple[int, int]]:
    """Return the common free slots for everyone within ``[day_start, day_end)``.

    ``busy`` contains one list of busy intervals per person.  Busy intervals
    may overlap, be unsorted, or extend outside the day.  A time is free for
    everyone exactly when nobody is busy then, so it suffices to merge all busy
    intervals (clipped to the day) and return the gaps between them.

    Only slots whose length is at least ``min_len`` are returned.  The result is
    sorted by start time.

    Runs in ``O(n log n)`` time, where ``n`` is the total number of busy
    intervals.
    """
    if day_start >= day_end:
        return []

    # Clip every busy interval to the day, then sort by start.
    clipped: list[tuple[int, int]] = []
    for person_busy in busy:
        for start, end in person_busy:
            if start < day_start:
                start = day_start
            if end > day_end:
                end = day_end
            if start < end:
                clipped.append((start, end))

    clipped.sort()

    free: list[tuple[int, int]] = []
    cursor = day_start

    for start, end in clipped:
        if start > cursor:
            # A gap exists; merge it if two busy intervals do not overlap.
            if start - cursor >= min_len:
                free.append((cursor, start))
        if end > cursor:
            cursor = end

    if cursor < day_end and day_end - cursor >= min_len:
        free.append((cursor, day_end))

    return free
