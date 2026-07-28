"""Enumerate one source file and construct each function's sugar.

Enumeration protocol only — one file at a time:

  path_source → SourceFile → functions() → fn.sugar()

No package-wide preconstruction, no call-frame populate, no subprocess.
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


def _source_call_binding_gap_row(error) -> dict[str, object]:
    return {
        "exception_type": type(error).__name__,
        "gap": {
            "owner": "SourceCallFrame.bind_node_actuals",
            "observed": str(error),
            "requested": "every call actual consumed by the authenticated frame",
            "fix": "bind or reject the unconsumed actual at the call frame",
        },
    }


def _typed_construction_row(error) -> dict[str, object] | None:
    """Serialize a known typed construction failure, or None if untyped."""
    from sugar_source_tree.panic import SourceTreePanic
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    if isinstance(error, ConstructionPanic):
        return _construction_panic_row(error)
    if isinstance(error, SourceTreePanic):
        return _source_tree_gap_row(error)
    if isinstance(error, SourceCallBindingGap):
        return _source_call_binding_gap_row(error)
    return None


def production_lift_testimony(path: Path, rel: str) -> dict[str, object]:
    """Enumerate one file and construct each function once."""
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    gaps: list[dict[str, object]] = []
    reporter = CollectingReporter()
    try:
        # Enumeration protocol: one authenticated construction door. A bare
        # SourceFile has no manager-resolution context and paints every With as
        # RuntimeSelectedContextManager, which is false typed-gap testimony.
        source_file = open_source_file_for_construction(
            path, root=path.parent, reporter=reporter
        )
    except BaseException as error:
        row = _typed_construction_row(error)
        if row is None:
            raise
        gaps.append(row)
        return {
            "kind": _TERMINAL_KIND,
            "outcome": OUTCOME_TYPED_GAP,
            "file": rel,
            "typed_gap_count": len(gaps),
            "typed_gaps": gaps,
        }
    for fn in source_file.functions():
        try:
            fn.sugar()
        except BaseException as error:
            row = _typed_construction_row(error)
            if row is None:
                raise
            gaps.append(row)
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
    """Enumerate one file, construct each function, emit one terminal row.

    Typed construction failures → ``typed-gap`` and exit 0.
    Any other exception propagates (bare-exception signal to the caller).
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
