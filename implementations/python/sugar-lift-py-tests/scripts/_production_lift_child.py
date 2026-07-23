"""Shared production-lift child body for the zero-tolerance floor scanners.

The floors (bare-exception, native-crash, timeout, silent) each isolate one
source file in a subprocess and observe how the CURRENT production construction
path behaves on it. This module is the ONE adapter every scanner's child uses so
they all lift through the exact census/production door -- there is no
scanner-only construction door.

The production door (identical to ``census.census``): construct every function
of a file once via ``SourceFile.from_path(...).functions()`` then ``fn.sugar()``.
The reporter witnesses nested gaps during construction.

Outcome taxonomy (the child EMITS one ``lift-terminal`` row; its absence on a
zero exit is the silent axis, and a signal death / timeout are observed by the
parent):
  - ``completed``  -- every function constructed with no gap.
  - ``typed-gap``  -- at least one sanctioned typed construction gap:
    tree ``SugarNotWritten`` or kit ``ConstructionPanic``. INTENTIONAL; NOT a
    failure; the floors do not count it red.
  - (bare exception) -- any OTHER exception propagates out of this child
    unhandled, so the child exits nonzero and the parent classifies it a bare
    Python exception. We never swallow it here.

Only the two typed gap types above are caught. Nothing else is.
"""

from __future__ import annotations

import json
from pathlib import Path

_TERMINAL_KIND = "lift-terminal"
OUTCOME_COMPLETED = "completed"
OUTCOME_TYPED_GAP = "typed-gap"


def _source_tree_gap_row(error) -> dict[str, object]:
    return {
        "exception_type": type(error).__name__,
        "gap": {
            "owner": error.owner,
            "observed": error.observed,
            "requested": error.requested,
            "fix": error.fix,
        },
    }


def _construction_panic_row(error) -> dict[str, object]:
    return {
        "exception_type": type(error).__name__,
        "gap": error.info.to_json(),
    }


def production_lift_testimony(path: Path, rel: str) -> dict[str, object]:
    """Construct once and return closed terminal testimony for every scanner."""
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from _production_source_file import (
        corpus_root_from_relative,
        production_source_file,
    )

    gaps: list[dict[str, object]] = []
    reporter = CollectingReporter()
    try:
        sf = production_source_file(
            path,
            root=corpus_root_from_relative(path, rel),
            reporter=reporter,
        )
    except SugarNotWritten as error:
        gaps.append(_source_tree_gap_row(error))
        sf = None
    except ConstructionPanic as error:
        gaps.append(_construction_panic_row(error))
        sf = None
    if sf is None:
        return {
            "kind": _TERMINAL_KIND,
            "outcome": OUTCOME_TYPED_GAP,
            "file": rel,
            "typed_gap_count": len(gaps),
            "typed_gaps": gaps,
        }
    for fn in sf.functions():
        try:
            fn.sugar()
        except SugarNotWritten as error:
            gaps.append(_source_tree_gap_row(error))
        except ConstructionPanic as error:
            gaps.append(_construction_panic_row(error))
    return {
        "kind": _TERMINAL_KIND,
        "outcome": OUTCOME_TYPED_GAP if gaps else OUTCOME_COMPLETED,
        "file": rel,
        "typed_gap_count": len(gaps),
        "typed_gaps": gaps,
    }


def production_lift_bootstrap_error() -> str | None:
    """Import the production construction door once. Returns an error string if
    the scanner infrastructure itself cannot bootstrap (so the parent reports it
    ONCE as an infrastructure failure, never multiplied into one bogus source
    failure per file), or None when the door is importable."""
    try:
        from sugar_source_tree.tree import SourceFile  # noqa: F401
        from sugar_source_tree.reporter import CollectingReporter  # noqa: F401
        from sugar_source_tree.panic import SugarNotWritten  # noqa: F401
        from sugar_lift_py_tests.gap.panic import ConstructionPanic  # noqa: F401
    except Exception as error:  # noqa: BLE001 -- reported once, by design
        return f"{type(error).__name__}: {error}"
    return None


def run_production_lift_child(path: Path, rel: str) -> int:
    """Lift one file through the production door and emit its terminal row.

    A sanctioned typed gap (``SugarNotWritten`` or kit ``ConstructionPanic``)
    anywhere in the file's construction marks the whole file ``typed-gap``
    (intentional) but does not stop scanning the rest. Any other exception is
    left to propagate -- that is the bare-exception signal.
    """
    print(json.dumps(production_lift_testimony(path, rel)), flush=True)
    return 0


def terminal_outcome(stdout: str) -> str | None:
    """The outcome of the last ``lift-terminal`` row in a child's stdout, or
    None when the child emitted none (the silent / missing-result axis)."""
    from typing import Mapping

    for line in reversed(stdout.splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind") == _TERMINAL_KIND:
            outcome = row.get("outcome")
            return str(outcome) if outcome is not None else None
    return None


# Outcomes that are NOT untyped failures: a clean completion or an intentional
# typed loud gap. Every floor treats these as non-red.
NON_FAILURE_OUTCOMES = frozenset({OUTCOME_COMPLETED, OUTCOME_TYPED_GAP})
