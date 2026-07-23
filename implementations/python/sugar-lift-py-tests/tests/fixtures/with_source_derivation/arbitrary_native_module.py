"""Renamed wrapper around a native manager whose protocol source is unavailable."""

from _thread import allocate_lock


def some_manager():
    return allocate_lock()
