"""Optional per-file-open profile for construction cost attribution.

Enabled only while a recensus (or other instrument) holds the contextvar.
Default is off — zero cost when unset. materialize_module records count+time
per module identity so a slow open names which dependency rebuilds dominate.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

# None = profiling off (production default).
_PROFILE: ContextVar[dict[str, Any] | None] = ContextVar(
    "sugar_source_tree_file_open_profile", default=None
)


def begin_file_open_profile() -> dict[str, Any]:
    """Start a profile bag for one file open; return it for the caller to fill."""
    bag: dict[str, Any] = {
        "module_materialize": {},  # module_key -> {count, s}
    }
    _PROFILE.set(bag)
    return bag


def current_file_open_profile() -> dict[str, Any] | None:
    return _PROFILE.get()


def end_file_open_profile() -> dict[str, Any] | None:
    """Clear the contextvar; return the bag (or None if never begun)."""
    bag = _PROFILE.get()
    _PROFILE.set(None)
    return bag


def record_module_materialize(module_key: str, elapsed_s: float) -> None:
    """Accumulate one materialize_module completion into the active profile."""
    bag = _PROFILE.get()
    if bag is None:
        return
    table = bag.setdefault("module_materialize", {})
    row = table.get(module_key)
    if row is None:
        table[module_key] = {"count": 1, "s": round(elapsed_s, 6)}
    else:
        row["count"] = int(row["count"]) + 1
        row["s"] = round(float(row["s"]) + elapsed_s, 6)


def summarize_module_materialize(bag: dict[str, Any] | None) -> dict[str, Any]:
    """Compact top offenders for running-counts (not the full map)."""
    if not bag:
        return {
            "modulesDistinct": 0,
            "materializeCalls": 0,
            "materialize_s": 0.0,
            "top": [],
        }
    table = bag.get("module_materialize") or {}
    total_calls = 0
    total_s = 0.0
    ranked: list[tuple[str, int, float]] = []
    for key, row in table.items():
        c = int(row.get("count") or 0)
        s = float(row.get("s") or 0.0)
        total_calls += c
        total_s += s
        ranked.append((str(key), c, s))
    ranked.sort(key=lambda item: (-item[2], -item[1], item[0]))
    top = [
        {"module": key, "count": c, "s": round(s, 4)} for key, c, s in ranked[:8]
    ]
    return {
        "modulesDistinct": len(table),
        "materializeCalls": total_calls,
        "materialize_s": round(total_s, 4),
        "top": top,
    }


class _TimedModuleMaterialize:
    """Context manager: time one materialize_module and record it."""

    def __init__(self, module_key: str) -> None:
        self.module_key = module_key
        self._t0 = 0.0

    def __enter__(self) -> "_TimedModuleMaterialize":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        record_module_materialize(self.module_key, time.perf_counter() - self._t0)
