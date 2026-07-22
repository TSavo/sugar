"""The roll call: the minority report built from the SOURCE side, zero reporters.

Construction is a roll call with two roles and one interface:

- **Roster** -- who SHOULD show up. A pure function of the source oracle and the
  enumeration protocol: enumerate every accountable unit of a file. It calls no
  ``sugar()``, threads no reporter, constructs nothing. Deterministic and
  content-addressed (each entry keyed by its oracle-minted CID).
- **Attendance** -- who DID show up. An INTERFACE (``Attendance``) that answers,
  per roster entry, one of three things: ``present-fact``, ``present-inert``
  (showed up, states nothing -- a docstring / pass / import), or nothing at all
  (absent). "Returned without answering" is not expressible: absence is the
  default, computed by difference, so a unit that crashes or vanishes mid-answer
  is still on the roster and still counts absent.

The **minority report is ``roster \\ attended``** -- the entries no present
answer covered. ``R`` is its size. ``R == 0`` iff every roster entry showed up.

This module is the ACCOUNTING mechanism and depends on NOTHING downstream: given
source it yields a total, honest report before a single reporter exists (with an
empty attendance the minority is the whole roster -- the honest "accounted for
nothing yet"). Threading real attendance (Phase 2) is a separate, monotonic pass
that can only move entries absent -> present; it can never fake a presence or
hide an absence, because it cannot remove anyone from a roster it did not build.
That decoupling -- report over (roster, Attendance-interface), never over
construction -- is what makes testing trivial: a stub attendance, no lift.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator, Mapping, Protocol, runtime_checkable


class Answer(Enum):
    """A roll-call answer. PRESENT_FACT and PRESENT_INERT both mean 'showed up'
    (accounted, Blue); an entry with no Answer is ABSENT (the minority, Yellow).
    ABSENT is a valid explicit answer too (a construction that loudly reported
    its own gap), but the roster never needs it stated -- absence is the default.
    """

    PRESENT_FACT = "present-fact"
    PRESENT_INERT = "present-inert"
    ABSENT = "absent"

    @property
    def is_present(self) -> bool:
        return self in (Answer.PRESENT_FACT, Answer.PRESENT_INERT)


@dataclass(frozen=True)
class RosterEntry:
    """One accountable unit, content-addressed. Identity is the CID."""

    cid: str
    kind: str
    name: str
    file: str
    start_line: int
    start_col: int

    def __hash__(self) -> int:  # keyed by CID alone
        return hash(self.cid)


@runtime_checkable
class Attendance(Protocol):
    """The report INTERFACE. The one seam between the source-side report and the
    construction side. It answers for a roster entry; ``None`` means the entry
    never answered (absent). Construction knows nothing of the report except
    that it implements this."""

    def answer_for(self, entry: RosterEntry) -> Answer | None: ...


class EmptyAttendance:
    """Nobody has answered. The honest moment-zero state: the minority is the
    entire roster."""

    def answer_for(self, entry: RosterEntry) -> Answer | None:  # noqa: D102
        return None


@dataclass(frozen=True)
class MappingAttendance:
    """Attendance from a plain ``{cid: Answer}`` mapping -- for tests and for any
    caller that has already collected answers out of band. No construction."""

    answers: Mapping[str, Answer]

    def answer_for(self, entry: RosterEntry) -> Answer | None:
        return self.answers.get(entry.cid)


def roster_entry_for(node, kind: str, name: str) -> RosterEntry:
    """A roster entry for one node -- its CID, kind, name, and locus. Reads the
    node's oracle-pinned fragment; constructs nothing."""
    lc = node.line_col_span()
    cid = node.fragment.seal().cid
    return RosterEntry(
        cid=cid,
        kind=kind,
        name=name,
        file=node.unit.filename,
        start_line=lc.start_line,
        start_col=lc.start_col,
    )


def function_roster(source_file) -> tuple[RosterEntry, ...]:
    """The roster at the function accounting level: every FunctionDef /
    AsyncFunctionDef in the file, in source order. Pure source enumeration --
    no ``sugar()``, no reporter. This is the ``functions`` census unit: a clean
    (present) count against this roster is exactly 'functions construct clean'.
    """
    from .nodes import AsyncFunctionDef, FunctionDef

    entries: list[RosterEntry] = []
    for node in source_file.nodes():
        if isinstance(node, (FunctionDef, AsyncFunctionDef)):
            entries.append(roster_entry_for(node, node.kind, node.name))
    return tuple(entries)


@dataclass(frozen=True)
class MinorityReport:
    """The report over a roster and an attendance interface. Honest by
    construction: the minority is exactly the roster entries no present answer
    covered. Nothing here consults construction."""

    roster: tuple[RosterEntry, ...]
    attendance: Attendance

    def _answer(self, entry: RosterEntry) -> Answer | None:
        return self.attendance.answer_for(entry)

    @property
    def present(self) -> tuple[RosterEntry, ...]:
        return tuple(
            e for e in self.roster
            if (a := self._answer(e)) is not None and a.is_present
        )

    @property
    def minority(self) -> tuple[RosterEntry, ...]:
        """roster \\ attended -- entries with no present answer. The absent
        never report themselves; the roster computes them by difference."""
        return tuple(
            e for e in self.roster
            if (a := self._answer(e)) is None or not a.is_present
        )

    @property
    def R(self) -> int:
        return len(self.minority)

    @property
    def is_clean(self) -> bool:
        """R == 0: there is no minority report -- every roster entry showed up."""
        return self.R == 0


def minority_report(
    source_file, attendance: Attendance | None = None
) -> MinorityReport:
    """Build the report for a file. With no attendance (Phase 1 / moment zero)
    the minority is the whole function roster -- total and honest, zero
    reporters, zero construction."""
    return MinorityReport(
        roster=function_roster(source_file),
        attendance=attendance if attendance is not None else EmptyAttendance(),
    )


def total_R(reports: Iterable[MinorityReport]) -> int:
    """R across many files: the size of the whole minority. R == 0 iff there is
    no minority report anywhere."""
    return sum(report.R for report in reports)
