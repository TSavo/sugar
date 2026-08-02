"""One supervised production pass → three process-axis projections.

CLASS
=====

``native_crash``, ``bare_exception``, and ``timeout`` are three classifiers over
the **same** :class:`FileTerminal` stream. Each used to call ``scan_paths`` and
re-lift every corpus file (~1421) independently — ~300% of one full supervised
pass for process axes alone.

Sound work: **one** ``scan_paths`` over the population, then three pure
projections. No cache required. Sound by construction: the classifiers always
read identical terminals; this only removes the redundant lifts.

COVERAGE LAW
============

Every input path gets exactly one terminal. Offenders are process outcomes of
the production door, not AST-local properties — there is **no** sound subtree
exclusion. This module removes **redundant passes**, not files. If a change
covers fewer files than ``len(paths)``, it is wrong.

Endgame (mr_brown): content-addressed terminal cache keyed on file CID sits
under this shared pass so unchanged corpus becomes near-zero work. Do not
restructure the supervisor loop here for cache — only the three callers merge.
"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Sequence

from _supervised_enum_supervisor import FileTerminal, scan_paths


class NativeCrashOffender(NamedTuple):
    file: str
    returncode: int
    signal: str
    stderr_tail: str


class BareExceptionOffender(NamedTuple):
    file: str
    returncode: int
    stderr_tail: str


class TimeoutOffender(NamedTuple):
    file: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SharedProcessFloorResult:
    """One terminal stream + three projected residual sets. Same coverage."""

    paths: tuple[Path, ...]
    terminals: tuple[FileTerminal, ...]
    native_crashes: tuple[NativeCrashOffender, ...]
    bare_exceptions: tuple[BareExceptionOffender, ...]
    timeouts: tuple[TimeoutOffender, ...]
    file_timeout: float

    @property
    def discovered(self) -> int:
        return len(self.terminals)

    def r_native_crashes(self) -> int:
        return len(self.native_crashes)

    def r_bare_exceptions(self) -> int:
        return len(self.bare_exceptions)

    def r_timeouts(self) -> int:
        return len(self.timeouts)

    def any_red(self) -> bool:
        return bool(self.native_crashes or self.bare_exceptions or self.timeouts)


def project_native_crash(row: FileTerminal) -> NativeCrashOffender | None:
    """Classifier: signal death of the production-door child."""
    if row.category != "native-crash":
        return None
    rc = row.returncode if row.returncode is not None else -1
    if rc >= 0 and not row.signal_name:
        return None
    if rc < 0:
        signal_number = -rc
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"signal-{signal_number}"
    else:
        signal_name = row.signal_name or f"returncode-{rc}"
    return NativeCrashOffender(
        file=row.file,
        returncode=rc,
        signal=signal_name,
        stderr_tail=row.stderr_tail,
    )


def project_bare_exception(row: FileTerminal) -> BareExceptionOffender | None:
    """Classifier: untyped failure terminal (not native, not timeout)."""
    if row.category != "bare-exception":
        return None
    return BareExceptionOffender(
        file=row.file,
        returncode=row.returncode if row.returncode is not None else 1,
        stderr_tail=row.stderr_tail,
    )


def project_timeout(
    row: FileTerminal, *, file_timeout: float
) -> TimeoutOffender | None:
    """Classifier: wall-clock kill of the in-flight file."""
    if row.category != "timeout":
        return None
    return TimeoutOffender(file=row.file, timeout_seconds=float(file_timeout))


def assert_full_coverage(
    paths: Sequence[Path], terminals: Sequence[FileTerminal], *, root: Path
) -> None:
    """Every path must produce one terminal. Fewer files ⇒ construction bug."""
    from _enum_floor_runtime import relative_to_root

    if len(terminals) != len(paths):
        raise RuntimeError(
            "process-floor coverage breach: "
            f"paths={len(paths)} terminals={len(terminals)}; "
            "every corpus file must get a terminal for every process axis "
            "(no sound subtree exclusion)"
        )
    expected = [relative_to_root(path, root) for path in paths]
    observed = [row.file for row in terminals]
    if expected != observed:
        # Order-preserving equality: scan is sequential over paths.
        missing = [rel for rel in expected if rel not in set(observed)]
        extra = [rel for rel in observed if rel not in set(expected)]
        raise RuntimeError(
            "process-floor coverage mismatch: "
            f"missing={missing[:5]}{('…' if len(missing) > 5 else '')} "
            f"extra={extra[:5]}{('…' if len(extra) > 5 else '')}"
        )


def shared_process_floor_pass(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: float = 30.0,
) -> SharedProcessFloorResult:
    """ONE supervised lift over *paths*; project all three process axes.

    Call this once from CI. Solo axis CLIs may call it and discard other
    residuals, but must not invent a second scan when the shared result exists.
    """
    if file_timeout > 30:
        raise ValueError("per-file timeout may not exceed 30 seconds")
    path_tuple = tuple(paths)
    terminals = tuple(
        scan_paths(path_tuple, root=root, file_timeout=float(file_timeout))
    )
    assert_full_coverage(path_tuple, terminals, root=root)

    native = tuple(
        offender
        for row in terminals
        if (offender := project_native_crash(row)) is not None
    )
    bare = tuple(
        offender
        for row in terminals
        if (offender := project_bare_exception(row)) is not None
    )
    timeouts = tuple(
        offender
        for row in terminals
        if (offender := project_timeout(row, file_timeout=float(file_timeout)))
        is not None
    )
    return SharedProcessFloorResult(
        paths=path_tuple,
        terminals=terminals,
        native_crashes=native,
        bare_exceptions=bare,
        timeouts=timeouts,
        file_timeout=float(file_timeout),
    )
