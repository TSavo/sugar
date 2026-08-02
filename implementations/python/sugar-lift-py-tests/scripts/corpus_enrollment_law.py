#!/usr/bin/env python3
"""R_unenrolled_corpus — criterion 1: every corpus file enters the sole door.

CRITERION 1: every authenticated-pandas file (and each of its functions) enters
the sole construction path:

    path_source → SourceFile (via open_source_file_for_construction)
               → functions() → fn.sugar()

That path is ``production_lift_testimony`` / supervised enum. Nothing else
counts as enrollment.

## Membership predicate (denominator) — what IS a corpus file

A path *p* is a member of the authenticated pandas corpus population for root
*R* iff ALL of:

1. *p* is a regular file
2. *p.suffix* == ``.py``
3. ``__pycache__`` is not among *p.parts*
4. *p* is under *R* (``p == R`` if *R* is a file, else *R* is an ancestor of *p*
   or *p* is *R*)
5. *p* is yielded by ``SourceTree(R).paths()`` — the sole discovery door

There is NO filter on manager spelling, ``targetSymbol``, ``pytest.raises``,
descendant call presence, or any other semantic property of the file body.
Whatever this predicate yields IS the file count. Never target a number.

Live authentication (``authenticated_pandas_corpus``) additionally requires the
manifest CID of the ordered (relative path, content CID) preimage to equal the
declared ``tool.sugar.measured-corpus.pandas-manifest-cid``. That authenticates
bytes; it does not change which *names* the tree discovers.

## Enrollment predicate — entered construction

A corpus file identity *f* (relative path as used by the census) is enrolled
iff a **terminal row** exists for *f* from the sole door
(``production_lift_testimony`` outcome of any kind: completed or typed-gap).
Terminal rows are the existence proof that the door ran.

    R_unenrolled_files = |denominator_paths − terminal_file_identities|

Function-level:

    A function is a member of the file's construction worklist iff it is
    yielded by ``SourceFile.functions()`` (FunctionDef / AsyncFunctionDef at
    any depth, source order). Enrollment at function grain requires the door
    to have iterated ``for fn in source_file.functions(): fn.sugar()``. Without
    a receipt that names function loci, R_unenrolled_functions is UNMEASURED.

## What this instrument is NOT

* Not a process-floor red/green on panics/crashes/timeouts (criterion 2).
* Not a recensus rank of residual owners.
* Not permission to drain construction gaps — report-first only.

## Ladder / retirement

Type system cannot enumerate an open vendor corpus. One door already exists
(``production_lift_testimony``); this auditor measures who never entered it.
Panic at contact for unenrolled is wrong: the honest state is a missing
terminal, not a mid-composition defect.

**Retire this shell when:** enrollment is existence by construction — the
census cannot *start* without a complete terminal set equal to
``SourceTree(authenticated_root).paths()``, so unenrolled is unrepresentable
and this count is permanently zero without a separate scanner.

SCOREBOARD_AUTHORITY = False
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import NamedTuple, Sequence


class EnrollmentReport(NamedTuple):
    denominator_files: int
    enrolled_files: int | None
    unenrolled_files: int | None
    unenrolled_identities: tuple[str, ...]
    measured_enrollment: bool
    note: str


def is_corpus_py_path(path: Path, *, root: Path) -> bool:
    """Structural file membership — sole discovery rules, no body semantics.

    Predicate (see module docstring). Consults path shape only.
    """
    root = root.resolve()
    path = path.resolve()
    if not path.is_file():
        return False
    if path.suffix != ".py":
        return False
    if "__pycache__" in path.parts:
        return False
    if root.is_file():
        return path == root
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def discover_corpus_paths_structural(root: Path) -> tuple[Path, ...]:
    """Path selection identical to ``SourceTree.paths`` (structural only).

    Kept free of sugar_source_tree imports so discrimination teeth can run
    without the full lift import graph. Production measure still cross-checks
    against ``SourceTree.paths()`` when that import is available.
    """
    root = root.resolve()
    if root.is_file():
        if is_corpus_py_path(root, root=root):
            return (root,)
        return ()
    ordered = tuple(
        sorted(
            path.resolve()
            for path in root.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        )
    )
    return ordered


def denominator_paths(root: Path) -> tuple[Path, ...]:
    """Live denominator: same set as SourceTree.paths() under root."""
    root = root.resolve()
    _log(f"corpus_enrollment phase=discover_structural status=start root={root}")
    structural = discover_corpus_paths_structural(root)
    _log(
        f"corpus_enrollment phase=discover_structural status=done "
        f"paths={len(structural)}"
    )
    bad = [p for p in structural if not is_corpus_py_path(p, root=root)]
    if bad:
        raise ValueError(
            "discovery yielded paths that fail is_corpus_py_path: "
            + ", ".join(str(p) for p in bad[:5])
        )
    try:
        from sugar_source_tree.tree import SourceTree

        _log("corpus_enrollment phase=sourcetree_crosscheck status=start")
        tree_paths = tuple(path.resolve() for path in SourceTree(root).paths())
        _log(
            f"corpus_enrollment phase=sourcetree_crosscheck status=done "
            f"paths={len(tree_paths)}"
        )
    except ImportError:
        _log(
            "corpus_enrollment phase=sourcetree_crosscheck status=skip "
            "reason=ImportError"
        )
        return structural
    if tree_paths != structural:
        raise ValueError(
            "SourceTree.paths() and structural discovery disagree — "
            "fix discovery to match SourceTree.paths exactly"
        )
    return tree_paths


def relative_file_identity(path: Path, *, corpus_root: Path) -> str:
    """Stable file identity used by recensus / process floors."""
    corpus_root = corpus_root.resolve()
    path = path.resolve()
    rel = path.relative_to(corpus_root).as_posix()
    return f"{corpus_root.name}/{rel}"


def terminal_file_identities_from_recensus(payload: dict) -> frozenset[str]:
    """Files that produced a terminal row (entered the sole door).

    Accepts control_effect_recensus result shape:
      denominator.enrolledFiles  — path set selected for the door
      missingFiles               — selected but no terminal
    or a flat list of terminal ``file`` fields under rows.

    Terminal identity = selected − missing, which is the existence proof
    that production_lift_testimony ran for that file.
    """
    denom = payload.get("denominator")
    if isinstance(denom, dict):
        enrolled = denom.get("enrolledFiles")
        missing = denom.get("missingFiles") or []
        if enrolled is None:
            raise ValueError("denominator.enrolledFiles missing")
        enrolled_set = {str(x) for x in enrolled}
        missing_set = {str(x) for x in missing}
        return frozenset(enrolled_set - missing_set)

    terminals: set[str] = set()
    for key in ("rows", "floor_rows", "terminals"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and "file" in row:
                terminals.add(str(row["file"]))
    if terminals:
        return frozenset(terminals)
    raise ValueError(
        "recensus payload has neither denominator.enrolledFiles nor terminal rows"
    )


def measure_enrollment(
    *,
    corpus_root: Path,
    recensus_payload: dict | None,
) -> EnrollmentReport:
    """Compute denominator live; enrollment only from a terminal receipt."""
    _log(f"corpus_enrollment phase=measure status=start corpus_root={corpus_root}")
    paths = denominator_paths(corpus_root)
    denom_ids = tuple(relative_file_identity(p, corpus_root=corpus_root) for p in paths)
    denom_n = len(denom_ids)
    _log(f"corpus_enrollment phase=denominator status=done files={denom_n}")
    if recensus_payload is None:
        _log(
            "corpus_enrollment phase=terminals status=skip "
            "reason=no_recensus enrollment=UNMEASURED"
        )
        return EnrollmentReport(
            denominator_files=denom_n,
            enrolled_files=None,
            unenrolled_files=None,
            unenrolled_identities=(),
            measured_enrollment=False,
            note=(
                "denominator live from SourceTree.paths(); enrollment UNMEASURED "
                "(no --from-recensus receipt). Do not invent enrolled=denominator."
            ),
        )
    _log("corpus_enrollment phase=terminals status=start")
    terminal = terminal_file_identities_from_recensus(recensus_payload)
    denom_set = set(denom_ids)
    # Unenrolled relative to the live denominator, not a curated list
    unenrolled = sorted(denom_set - terminal)
    # Also surface terminals not in denominator (population drift)
    extra = sorted(terminal - denom_set)
    enrolled_n = len(terminal & denom_set)
    _log(
        f"corpus_enrollment phase=terminals status=done "
        f"terminals={len(terminal)} enrolled={enrolled_n} "
        f"unenrolled={len(unenrolled)} drift_extra={len(extra)}"
    )
    note = (
        f"live denominator={denom_n}; terminals={len(terminal)}; "
        f"unenrolled={len(unenrolled)}"
    )
    if extra:
        note += f"; terminals_outside_denominator={len(extra)} (population drift)"
    return EnrollmentReport(
        denominator_files=denom_n,
        enrolled_files=enrolled_n,
        unenrolled_files=len(unenrolled),
        unenrolled_identities=tuple(unenrolled),
        measured_enrollment=True,
        note=note,
    )


def membership_predicate_source() -> str:
    """Source of the membership predicate — teeth inspect this, not prose."""
    import inspect

    return "\n".join(
        (
            inspect.getsource(is_corpus_py_path),
            inspect.getsource(discover_corpus_paths_structural),
            inspect.getsource(denominator_paths),
        )
    )


_FORBIDDEN_IN_PREDICATE = (
    "targetSymbol",
    "pytest.raises",
    "contextlib.suppress",
    "manager",
    "descendant",
)


def predicate_has_vendor_or_call_filter(source: str) -> list[str]:
    """Return forbidden tokens if the membership predicate smuggles filters."""
    hits = [tok for tok in _FORBIDDEN_IN_PREDICATE if tok in source]
    return hits


def format_report(report: EnrollmentReport) -> str:
    lines = [
        "corpus_enrollment_law",
        f"R_unenrolled_files = {report.unenrolled_files if report.measured_enrollment else 'UNMEASURED'}",
        f"denominator_files = {report.denominator_files}",
        f"enrolled_files = {report.enrolled_files if report.measured_enrollment else 'UNMEASURED'}",
        f"measured_enrollment = {report.measured_enrollment}",
        f"note = {report.note}",
        "",
        "Construction door: path_source → SourceFile → functions() → sugar()",
        "Membership: SourceTree.paths() under authenticated pandas root; no body filters.",
        "",
        "Unenrolled identities:",
    ]
    if not report.measured_enrollment:
        lines.append("(enrollment not measured — supply --from-recensus)")
    elif not report.unenrolled_identities:
        lines.append("(none)")
    else:
        for ident in report.unenrolled_identities[:50]:
            lines.append(ident)
        if len(report.unenrolled_identities) > 50:
            lines.append(f"... +{len(report.unenrolled_identities) - 50} more")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(
                encoding="utf-8", errors="backslashreplace", line_buffering=True
            )
        except (AttributeError, ValueError, TypeError):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, ValueError):
                pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Pandas package root. If omitted, try authenticated_pandas_corpus().",
    )
    parser.add_argument(
        "--from-recensus",
        type=Path,
        default=None,
        help="control_effect_recensus JSON receipt (denominator + terminals).",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write machine-readable report.",
    )
    args = parser.parse_args(argv)

    hits = predicate_has_vendor_or_call_filter(membership_predicate_source())
    if hits:
        print(
            "CORPUS-ENROLLMENT LAW RED: membership predicate smuggles filters: "
            + ", ".join(hits),
            file=sys.stderr,
        )
        return 1

    corpus_root = args.corpus_root
    if corpus_root is None:
        try:
            from sugar_lift_py_tests.authenticated_pytest import (
                authenticated_pandas_corpus,
            )

            corpus = authenticated_pandas_corpus()
            corpus_root = corpus.root
            print(
                f"# authenticated corpus file_count={corpus.file_count} "
                f"manifest={corpus.manifest_cid}",
                flush=True,
            )
        except Exception as error:
            print(
                "CORPUS-ENROLLMENT LAW: denominator UNMEASURED — "
                f"cannot authenticate corpus ({type(error).__name__}: {error}). "
                "Pass --corpus-root or run where authenticated_pandas_corpus works.",
                file=sys.stderr,
            )
            return 2

    payload = None
    if args.from_recensus is not None:
        try:
            payload = json.loads(args.from_recensus.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            print(
                f"CORPUS-ENROLLMENT LAW RED: cannot read --from-recensus: "
                f"{type(error).__name__}: {error}",
                file=sys.stderr,
            )
            return 1

    try:
        report = measure_enrollment(
            corpus_root=corpus_root, recensus_payload=payload
        )
    except Exception as error:
        print(
            f"CORPUS-ENROLLMENT LAW RED: measurement failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print(format_report(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(
                {
                    "denominator_files": report.denominator_files,
                    "enrolled_files": report.enrolled_files,
                    "R_unenrolled_files": report.unenrolled_files,
                    "unenrolled_identities": list(report.unenrolled_identities),
                    "measured_enrollment": report.measured_enrollment,
                    "note": report.note,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    if not report.measured_enrollment:
        print(
            "CORPUS-ENROLLMENT: enrollment UNMEASURED (no recensus receipt). "
            "Denominator alone is not criterion-1 zero.",
            file=sys.stderr,
        )
        return 2
    if report.unenrolled_files and report.unenrolled_files > 0:
        print(
            f"CORPUS-ENROLLMENT LAW RED: R_unenrolled_files={report.unenrolled_files}",
            file=sys.stderr,
        )
        return 1
    print("CORPUS-ENROLLMENT LAW GREEN: R_unenrolled_files=0", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
