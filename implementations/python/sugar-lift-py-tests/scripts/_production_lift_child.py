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
  - ``typed-gap``  -- at least one ``SugarNotWritten``: an INTENTIONAL typed,
    loud source-tree gap. NOT a failure; the floors do not count it red.
  - (bare exception) -- any OTHER exception propagates out of this child
    unhandled, so the child exits nonzero and the parent classifies it a bare
    Python exception. We never swallow it here.

``SugarNotWritten`` is caught (it is the sanctioned typed gap); nothing else is.
"""

from __future__ import annotations

import json
from pathlib import Path

_TERMINAL_KIND = "lift-terminal"
OUTCOME_COMPLETED = "completed"
OUTCOME_TYPED_GAP = "typed-gap"


def production_lift_bootstrap_error() -> str | None:
    """Import the production construction door once. Returns an error string if
    the scanner infrastructure itself cannot bootstrap (so the parent reports it
    ONCE as an infrastructure failure, never multiplied into one bogus source
    failure per file), or None when the door is importable."""
    try:
        from sugar_source_tree.tree import SourceFile  # noqa: F401
        from sugar_source_tree.reporter import CollectingReporter  # noqa: F401
        from sugar_source_tree.panic import SugarNotWritten  # noqa: F401
    except Exception as error:  # noqa: BLE001 -- reported once, by design
        return f"{type(error).__name__}: {error}"
    return None


def run_production_lift_child(path: Path, rel: str) -> int:
    """Lift one file through the production door and emit its terminal row.

    A ``SugarNotWritten`` anywhere in the file's construction marks the whole
    file ``typed-gap`` (intentional) but does not stop scanning the rest. Any
    other exception is left to propagate -- that is the bare-exception signal.
    """
    from sugar_source_tree.tree import SourceFile
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.panic import SugarNotWritten

    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(path), reporter=reporter)
    typed_gap = False
    for fn in sf.functions():
        try:
            fn.sugar()  # ONE construction; nested gaps self-report
        except SugarNotWritten:
            typed_gap = True  # sanctioned typed loud gap -- keep scanning
    outcome = OUTCOME_TYPED_GAP if typed_gap else OUTCOME_COMPLETED
    print(
        json.dumps({"kind": _TERMINAL_KIND, "outcome": outcome, "file": rel}),
        flush=True,
    )
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
